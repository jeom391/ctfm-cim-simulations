# C2C 웹 입력과 측정 화면 개선 (2026-09-23)

`docs/c2c-backend-2026-09-22.md`에서 "프론트는 범위 밖"으로 남겼던 웹 입력을 연결하고, 05에서 보류됐던
측정 화면 불편 세 가지를 처리했다. 백엔드 계약(`schema_version` 1.3.0)은 변경하지 않았다.

## 1. C2C 웹 입력

**계약.** 1.3.0 요청은 `effects.c2c`, `n_reprogram`(1~100), 그리고 C2C on일 때 **모든**
`profile_refs[i].c2c = {cv_percent, source:"manual_assumption"}`를 요구한다. C2C off이면 `n_reprogram`은
1이어야 하고 어떤 ref도 `c2c`를 가져선 안 된다(미리 채워진 것처럼 보이면 안 되기 때문).

**구현.**

- `apps/web/src/lib/api/generated.ts`를 현재 `openapi.json`으로 재생성했다. 이전 파일은 1.2.0 시절이라
  `effects.c2c`가 `false` 상수, `n_reprogram`이 `1` 상수로 고정돼 있어 타입 수준에서 C2C를 보낼 수 없었다.
- `buildExperiment`는 **C2C on일 때만 `1.3.0`을 보낸다.** off이면 기존과 바이트 단위로 같은 1.2.0 요청이
  나가므로 이전 실행 기록과의 비교가 깨지지 않는다.
- 프로파일 revision마다 CV를 따로 입력받는다. 한 프로파일에 입력했다고 다른 프로파일이 물려받지 않으며,
  누락·음수·비숫자는 실행 전에 거부한다. CV 0은 유효한 입력으로 통과시킨다.
- 실행 예산 표시가 `n_reprogram`을 곱하도록 고쳤다. 이전에는 재기록 횟수가 빠져 실제보다 작게 보였다.
- 결과 표에 `reprogram_index` 열을 추가했다.

**UI 문구에서 유지한 구분.** "실측 C2C 분포가 아니라 공학적 가정", CV%는 평균 1의 로그정규 배율로
변환돼 **재기록마다 셀·plane별로 새로 뽑히고** D2D는 같은 배열에서 고정, Gmin/Gmax 자동 clipping 없음.

## 2. 측정 화면 — 05에서 보고된 불편 세 가지

| 보고된 불편 | 처리 |
| --- | --- |
| LTP/LTD 한 쌍 입력이 어렵다 | 파일 이름에서 방향(LTP/LTD)과 조건 ID를 추정해 미리 채우고, **"현재 LTP n개 · LTD m개"** 집계를 상시 표시한다. 두 방향이 모두 있어야 `common` 풀이 생긴다는 점을 그 자리에서 설명한다. |
| 입력칸이 복잡하다 | 계측기 export의 열 이름(`Time` / `MeasResult1_value` / `MeasResult2_value` 등)에서 canonical 열과 단위를 추정해 미리 채운다. A1 LTP/LTD 한 쌍 기준으로 직접 골라야 하던 드롭다운 12개가 0개가 된다. |
| 선택 비활성화 이유가 불명확하다 | 분석 시작 버튼이 말없이 죽어 있지 않고, 시뮬레이터와 같은 방식으로 **막고 있는 이유 한 줄**을 항상 보여준다(`데이터셋 2: 열·단위·조건을 확인해 주세요.` 등). |

**추정은 확인을 대체하지 않는다.** 미리 채운 값은 "추정값이므로 원본 미리보기와 대조하라"고 화면에
명시하고, 데이터셋별 확인 체크박스와 `buildAnalysis` 재검증은 그대로 남는다. 소자 ID는 추정하지 않는다.
분석 종류 탭을 바꾸면 그 종류의 canonical 열로 다시 추정하되, 사용자가 입력한 값은 보존한다.

`apps/web/vite.config.ts`의 dev proxy 대상은 `CTFM_API_URL`로 바꿀 수 있게 했다. 기본값은 기존과 같은
`http://127.0.0.1:8000`이며, 기존 runtime과 분리된 검증용 인스턴스를 띄울 때 필요하다.

## 3. 검증

자동 테스트와 **실제 브라우저 실행**을 구분해 기록한다.

**자동 테스트**

- 웹 `npm test` 21 passed(payload 기준), `tsc --noEmit` + `vite build` 통과.
  신규: C2C off의 1.2.0 유지, C2C on의 1.3.0 + per-ref CV, CV 0 허용/누락·음수·비숫자 거부,
  두 번째 프로파일이 첫 프로파일 CV를 물려받지 못함, `n_reprogram` 경계와 예산 곱셈,
  실제 참조 파일 헤더에 대한 추정 결과가 `data/reference/ltp-ltd-2026-09-21/manifest.json`의
  `column_mapping`/`units`와 일치, 추정해도 확인·소자 ID는 여전히 필요.
- 요청 JSON 두 형태(C2C on / off)를 `packages/contracts`의 실제 스키마로 직접 검증.
- Python 전체 `pytest -q` **322 passed, 5 skipped**(exit 0) — 06 기준과 같고 회귀 없음. skip 5건은 모두 원본 A1 워크북(`CTFM_A1_FILE`) 미제공으로 인한 기존 skip.
- 계약 drift 검사 `export_schemas.py --check` / `export_openapi.py --check` 모두 current(exit 0).

로그와 결과 JSON은 [`evidence/c2c-web-2026-09-23/`](../evidence/c2c-web-2026-09-23/)에 있다.

**실제 브라우저 (Chrome, 격리 runtime: 전용 `CTFM_STORAGE_ROOT`, API 포트 8100)**

1. 측정 화면에서 `A1_LTP.csv`·`A1_LTD.csv`를 **파일 선택으로 업로드** → 방향·조건 ID·열·단위가 모두
   자동으로 채워짐(사람이 고른 드롭다운 0개). 소자 ID만 입력하고 두 데이터셋 확인.
2. 분석 실행 → succeeded, **candidate 1020 / positive 1020**. 풀은 `combined`·`ltp`·`ltd` 사용 가능,
   `common`은 두 방향의 겹치는 구간이 없어 불가 — 05에서 관측된 것과 같으며 UI 결함이 아니다.
3. 해당 분석으로 프로파일 초안 생성 후 revision 1 발행(reviewer·review_note 필요).
4. 시뮬레이터에서 그 프로파일을 선택하고 **C2C on, CV 5%, 재기록 2회**로 실행.
   전송된 요청은 `schema_version: "1.3.0"`, `profile_refs[0].c2c = {cv_percent: 5, source: "manual_assumption"}`,
   `n_reprogram: 2`, 예산 표시 2/2,000.
5. 결과 succeeded, run 5건:

   | kind | reprogram_index | accuracy |
   | --- | --- | --- |
   | D0 | — | 0.9645 |
   | D1 | — | 0.9643 |
   | M0 | — | 0.9644 |
   | ALL | 0 | 0.9644 |
   | ALL | 1 | 0.9641 |

   두 재기록이 **서로 다른 값**을 냈다(0.9644 / 0.9641) — 재기록마다 C2C를 새로 뽑는다는 계약이
   실제 실행에서 지켜짐을 뜻한다.

**이 수치의 한계.** 단일 조건(A1) · 단일 checkpoint · combined/fixed_reference · 배열 1 · ADC off ·
D2D off · year 0의 한 사례다. CV 5%는 **수동 가정**이지 실측 C2C가 아니다. 이 표로 C2C의 영향 크기나
소자 우열을 계산하지 않는다.

## 4. 남은 것

1. **실측 IV/Retention 파서** — 원본 `관련 자료/IV Sweep/`·`관련 자료/Retention/`가 이 체크아웃에
   없어(gitignore 대상이자 실제 폴더 부재) 착수하지 못했다. 레이아웃 문제는
   [백엔드 검증 2절](verification-backend-batch-2026-09-23.md)에 정리돼 있다.
2. **NeuroSim preset과 실제 PPA** — 엔진은 확보돼 있다(같은 문서 3절 정정). preset 값은 소자팀 결정.
3. **필드 계약 이름 통일** (`mapping_errors`/`mapping_metrics`, `adc`/`adc_metrics`). 프런트는 현재
   두 이름을 모두 허용한다.
4. 측정 화면의 나머지 05 항목: 순차 파일 추가, 방향 중복/누락 검증, 삭제/재추가 흐름.
