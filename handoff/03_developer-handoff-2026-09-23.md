> **2026-09-23 게시 시 추가 확인 (Claude, `local_report/07_TASK_publish-handoff.md` 수행 중 작성):** 아래 본문은 Codex가 01~05 검토와 06 재확인 "화면"만 근거로 작성한 초안이며, 초안 자체가 "06 원본 보고서와 diff를 읽지 못했다"고 명시하고 있었다. 이 절은 그 갭을 `local_report/06_REPORT_backend-batch.md` 원본, `local_report/evidence/06/`의 실제 로그, `git diff 96fb9bc..2b0a830`을 직접 대조해 메운 것이다. 아래 "5. 작업 06" 절의 "미확인" 항목에 구체적인 답을 채워 넣었고, 이 문서를 포함한 커밋은 `claude/adc-order-comparison` 브랜치로 `origin`에 push된다(강제 push/main 자동 merge 아님) — 즉 "코드가 GitHub에서 확인되지 않는다"는 아래 3번째 줄의 상태는 이 게시로 해소된다. **다만 이것은 "모든 기능이 완료됐다"는 뜻이 아니다** — 06 작업은 대부분 검증(fix 아님)이었고, NeuroSim 엔진 실행·실측 IV/Retention 연결·05 프론트는 여전히 blocked/보류 상태 그대로다.

---

> **2026-09-23 후속 작업 (Claude, 같은 날 두 번째 세션):** 이 문서 아래 본문의 두 가지 상태가 실제와 달라 정정한다. ① **NeuroSim 엔진은 있다.** 5절의 "B(NeuroSim 실행) blocked — 엔진 checkout 자체가 없음"은 **오판**이었다. `/opt/ctfm-engines/neurosim`이 문서 기록과 같은 commit `ac828e67…`로 존재하고 바이너리도 빌드돼 있으며, `verify_neurosim_adapter.py` 4개 검사 전부 통과(exit 0), `mnist_mlp_v1`을 subArray 256에서 실제로 완주시켰다(returncode 0). 남은 차단 요인은 엔진이 아니라 **preset 값(A1~A7·B1~B6 전부 null)**이며 이는 소자팀 결정이므로 채우지 않았다. ② **C2C 웹 입력과 측정 화면 개선은 이제 연결됐다** — 4절 "웹 C2C 입력은 04까지 미연결"과 6절 "프론트 05 보류"의 해당 범위는 이 세션에서 구현·검증했다. 실제 브라우저로 A1 LTP/LTD 두 파일 업로드 → 분석(1020 states) → 프로필 발행 → C2C on(CV 5%, 재기록 2회) 시뮬레이션 실행까지 통과했다. 상세는 [docs/c2c-web-input-2026-09-23.md](../docs/c2c-web-input-2026-09-23.md). ③ **여전히 남은 것**: 실측 IV/Retention 파서(원본 `관련 자료/` 폴더가 이 체크아웃에 없어 미착수), NeuroSim preset과 실제 PPA 수치, `mapping_errors`/`adc` 필드 계약 이름 통일.

---

# 개발 담당 인수인계 — 2026-09-23

> **먼저 코드 전달 상태를 확인하세요.** 이 문서를 올리기 직전 원격 main은 `6c590ea`였고, 원격 UI 브랜치는 `05a872d`였습니다. Claude의 최신 로컬 브랜치 `claude/adc-order-comparison`, HEAD `2b0a830`은 GitHub에서 확인되지 않았습니다. **이 문서 업로드는 최신 구현 코드 업로드나 병합을 뜻하지 않습니다.**

## 1. 읽는 순서와 확인 수준

1. 이 문서로 구현 상태와 코드 전달 문제를 파악합니다.
2. 최신 작업 브랜치와 원본 보고서를 전달받습니다.
3. [하드웨어 기준](../docs/spec/08-hardware-baseline.md), [설계 근거](../docs/research/hardware-baseline-evidence.md), [개발 마무리 계획](../docs/completion-plan-2026-09-21.md)을 읽습니다.
4. [2026-09-21 검증 기록](../docs/verification-2026-09-21.md)과 후속 작업 01~06 보고서를 비교합니다.

증거 수준:
- **직접 검토**: Codex가 해당 시점 로컬 diff·보고서를 읽고 명시한 테스트를 재실행했습니다.
- **Claude 보고**: 실행 로그 또는 보고서에서 확인했으며 Codex가 해당 실행을 반복하지 않았습니다.
- **06번 화면 보고만 확인**: 사용자가 전달한 Claude 재확인 화면에 근거합니다. 원본 06번 보고서와 코드 diff는 이번 인수인계 **초안 작성 시점**에는 읽지 못했습니다 (2026-09-23 게시 시 위 상단 노트에서 보완됨).

Codex 로컬 명령 도구의 `registered runtime ownership is missing` 오류 때문에 마지막 원본 검토와 git push는 수행하지 못했습니다. 대신 연결된 GitHub 도구로 원격 브랜치/커밋 상태를 확인하고 이 문서만 게시했습니다. 06번 작업을 전부 검수 완료한 문서로 읽으면 안 됩니다.

## 2. 작업 브랜치 전달이 최우선

원본 작업 위치:
`tmp/fix-measurement-csv` (worktree; 로컬 절대 경로는 사용자 PC 한정이므로 팀원 checkout에서는 저장소 루트 기준 상대 경로로 읽으세요.)

소통 자료:
`local_report/` (팀 공유 저장소에는 포함되지 않을 수 있음 — 아래 5번 참고)

사용자 첨부 화면의 Claude 재확인 내용:
- 브랜치 `claude/adc-order-comparison`, HEAD `2b0a830`.
- 미커밋 추적 변경 없음. `.bootstrap/`, `.claude/`는 기존 미추적 항목.
- 보고서/증거 파일 3개가 디스크에 존재.
- Wi-Fi 재연결 후 저장 상태만 조회했으며, 중단된 항목 없이 06 작업이 보고 후 종료됐다고 설명.
- 포트 8100/8000에 해당 작업의 실행 프로세스가 없다고 확인.

이는 Claude가 확인한 내용이며 Codex가 로컬에서 독립 확인한 것은 아닙니다.

코드 보유자는 먼저 해당 worktree에서 상태와 remote를 확인한 뒤 **기존 작업 브랜치를 보존하여 push**해야 합니다. main에 강제 덮어쓰기하거나 코드/데이터 전체를 일괄 add하지 않습니다. branch push 후 팀원이 fetch하여 최신 커밋을 확인하고 PR로 검토합니다. 이 인수인계 문서가 main에 새로 추가됐으므로 이후 병합 시 함께 보존합니다.

별도로 전달할 자료:
- `local_report/06_REPORT_backend-batch.md` 원본 및 `evidence/06/`의 실제 검증 근거.
- 01~05의 TASK/REPORT/REVIEW 중 재현에 필요한 문서.
- 최신 구현의 docs 및 엔진 patch/빌드 재현 방법(실제로 생성됐다면).
- runtime DB/checkpoint는 GitHub에 일괄 업로드하지 않습니다. 필요할 경우 별도 전달하거나 재생성하고 해시/경로를 기록합니다.
- `관련 자료` 전체는 GitHub에 있다고 가정하지 않습니다. 공유 LTP/LTD는 [고정 CSV와 manifest](../data/reference/ltp-ltd-2026-09-21/README.md)를 사용합니다.

## 3. 완료된 구현과 검증 범위

| 작업 | 마지막 검토 기준 | 구현/결과 | 검증 한계 |
| --- | --- | --- | --- |
| 기존 CSV 분석 경로 | main 6c590ea | 최신 A1~A5 CSV 파싱·분석·프로필 생성, 일부 HTTP/브라우저 확인 | 모든 측정 종류·웹 조합 검증 완료 아님 |
| 분석 결과 UI 경량화 | 05a872d | 큰 JSON 기본 렌더링 줄임, 상태 선택 페이지 나눔 | 원격 별도 브랜치, main 미병합 상태로 확인됨 |
| 01/01A ADC 비교 | c14b150 | 동일 profile/checkpoint로 두 ADC 순서 비교, 실패/설정 불일치 검증 | Codex 가드 테스트 14개 및 저장 실측 응답 replay 통과 |
| 02 schema 최신성 | 274b2fc | Windows CRLF와 생성기 LF의 바이트 차이 해결 | .gitattributes만 변경; Codex 계약 66개 및 두 --check 통과 |
| 03 C2C 수학 모듈 | 617fe26 | 수동 CV의 평균1 로그정규 배율, 재기록/plane별 RNG | Codex 관련 34개 통과; 실측 분포 검증 아님 |
| 04 C2C 백엔드 | 1f021ff | API→worker→실행→결과/export 연결, 반복 수 집계 수정 | Codex 관련 129개 및 schema 검사 통과; 실제 smoke는 Claude 로그 확인 |
| 05 선행 문구 정정 | 96fb9bc | 재기록 통계와 배열 통계의 설명 구분 | 코드 diff 확인; 주요 프론트 개선 미착수 |
| 06 일괄 작업 | **원본 06_REPORT + evidence/06 + diff 대조 완료 (2026-09-23)** | 아래 5절 참고 — A(측정 백엔드 핵심 경로) tested-measured, B/C6(NeuroSim 실행) blocked, A3(실측 IV/Retention) blocked, 소스 코드 변경 없음(문서 1건만) | 원본 보고서·diff 직접 대조로 상태 확정. "코드 결함 없음"과 "모든 기능 완료"는 다름 — B/A3는 미완료로 분류 |

### 정확도 수치의 구분

- 기존 09-21 실행: D0 96.45%, M0 96.44%, ADC 포함 95.88%. 디지털 대비 0.57%p, M0 대비 ADC 추가 영향 0.56%p.
- 작업 01 동일 checkpoint 비교: D0 96.51%, D1 96.50%, M0 96.41%; 차감 후 ADC 95.78%, 개별 ADC 후 차감 96.20%. A1 combined/fixed_reference, tile64, ADC6, 소자 비이상성 off의 단일 비교 사례입니다.
- 작업 04 A1 profile/checkpoint 재사용, 수동 C2C CV5%, 배열1·재기록2·year0·ADC off: 96.40%, 96.36%, 평균96.38% (Claude 실측 프로필 실행 로그).
- **작업 06 (신규, 격리 인스턴스 재실행)**: A1 신규 checkpoint(`fecc878f-51f5-4fc8-a261-0d7a13101d30`)로 D0 96.51%, D1 96.50%, M0 96.41%, ALL 95.78% — 작업 01과 **동일 조건·동일 수치**로 재현됨(새 checkpoint 학습, 값 강제 아님). `--compare-adc-orders`로 같은 checkpoint에서 ADC 순서만 바꾼 비교도 재실행: `accuracy_delta_pp = -0.42`(모든 비교 불변식 통과).
- 서로 다른 조건/체크포인트 수치를 섞어 개선량이나 소자 우열을 계산하지 않습니다. 수동 C2C는 실측 C2C가 아닙니다.

## 4. C2C 계약과 유지해야 할 의미

이 항목은 1f021ff에서 검토한 상태입니다.

- 요청 1.3.0에서 profile revision별 `c2c: {cv_percent, source: "manual_assumption"}` 입력.
- 1.2.0은 기존 의미 보존: C2C off, n_reprogram=1.
- C2C on일 때 모든 profile의 유한한 비음수 CV%를 명시. 측정 profile을 덮어쓰지 않음.
- n_reprogram 1~100, 실행 예산 profiles×pools×mappings×arrays×n_reprogram×years ≤ 2000.
- c=CV/100, s=sqrt(log(1+c²)), f=exp(-s²/2+sZ).
- G_program=G_nominal×D2D×C2C, 이후 Retention 적용.
- D2D는 같은 배열에서 고정, C2C는 재기록마다 셀/plane별 생성. 이미지·시간·ADC 순서가 바뀐다고 다시 뽑지 않음.
- 자동 Gmin/Gmax clipping 금지. 범위 초과율과 factor 자체의 실효 CV 기록.
- 배열별 재기록 평균과 같은 배열 내 재기록 분포를 구분(**06에서 이 두 문구가 서로 바뀌어 표시되던 버그를 수정, commit `96fb9bc`, 전용 테스트 추가**). 실패/누락 표본은 분모와 함께 보고.
- 웹 C2C 입력은 04까지 미연결. **06의 지시 범위에도 프론트는 명시적으로 제외**되어 있었고, 실제로 06에서 프론트 코드는 전혀 수정되지 않았음을 diff로 확인(`git diff 96fb9bc..2b0a830`은 `handoff/02_measurement-fix-and-next-steps.md` 9줄 추가뿐).

참고 구현 문서 `docs/c2c-core-module-2026-09-22.md`, `docs/c2c-backend-2026-09-22.md`는 로컬 작업 브랜치에 작성됐으므로 브랜치 전달 후 확인합니다.

## 5. 작업 06 — 확인된 것 (2026-09-23, 원본 보고서·evidence·diff 대조 완료)

사용자 첨부 Claude 화면에서 확인했던 저장 로그/종료 코드는 원본 `local_report/06_REPORT_backend-batch.md`와 `local_report/evidence/06/`을 직접 열어 대조한 결과 **일치했다**:
- pytest -q (TMPDIR 환경 문제 수정 후 재실행): **322 passed / 5 skipped**, exit 0 — `evidence/06/pytest-full-suite-322-passed.log`.
- measured_workflow.py A1~A5 (격리 API+worker, 포트 8100, 전용 storage root): exit 0 — `evidence/06/measured-workflow-A1-A5.log`. A1~A5 전 조건 업로드→분석(1020 states)→프로필 발행→ZIP export 성공.
- --compare-adc-orders (A1): exit 0 — `evidence/06/measured-workflow-A1-compare-adc-orders.log`. 동일 profile/checkpoint에서 ADC 순서만 바꾼 비교, 모든 비교 불변식 통과.
- export_openapi.py / export_schemas.py --check: 세션 내 종료 코드 0을 직접 관측했으나 별도 로그 파일로 저장되지 않았음 — **06 원본 보고서 자체도 이를 "로그 없음"으로만 표시하고 통과로 확정하지 않았다.** 이 문서도 동일하게 취급한다.
- 이번 세션이 직접 띄운 격리 API/worker(포트 8100)는 06 종료 시 모두 정지됨을 PID·포트 재조회로 확인. 05에서 관찰됐던 기존 포트 8000 서버는 06 재확인 시점에 이미 (이 세션과 무관하게) 중단돼 있었음.

**이제 구체적으로 답할 수 있는 것 (초안 작성 시점의 "미확인" 항목):**

- **06 A/B/C/D 각 묶음의 implemented/tested/blocked 상태**:
  - A(측정 백엔드): A1·A2(a,b,d,e)·A4는 tested-measured(위 정확도 수치 참고) 또는 기존 단위 테스트로 통과 확인. A2(c) 동일 기록 ADC/시간 비교는 단위 테스트 + 실제 HTTP 비교 실행 둘 다 통과. A2(f) 취소는 worker 단위 테스트로만 커버(C2C와 결합한 통합 테스트는 없음, 새로 만들지 않았다고 명시). A2(g) export 축-표본수 일치는 합성 단위 테스트로만 커버(실측 실행에서는 실패 0건이라 "일부 실패 시 분모 감소" 케이스를 관측하지 못함). **A3(실측 IV/Retention 연결)는 blocked** — 원본 파일은 실제 존재(`관련 자료/IV Sweep/`, `관련 자료/Retention/`)하지만 IV는 한 시트에 Vg/Id/Ig가 여러 번 반복되는 레이아웃, Retention은 program/erase가 서로 다른 time 축이라 현재 파서(`ctfm.measurement`)가 인식하는 형식과 다름 — C2C와 동일 원칙으로 새 파서를 만들지 않았다. A5(필드 계약, `adc`/`mapping_errors`)는 기존 gap 재확인만 하고 이름 변경은 하지 않음(지시 준수).
  - B(NeuroSim 실행): **blocked**. 이번 세션의 실제 WSL 환경(Ubuntu, g++13.3.0 확인됨)에 `/opt/ctfm-engines/neurosim` 등 엔진 checkout 자체가 없음을 전체 파일시스템 검색(`find / -iname '*neurosim*'`)으로 직접 확인. `docs/implementation-status.md`에 기록된 과거 빌드 성공(commit `ac828e6723bf077c9b1423c5c72ff6e4981e90f4`)은 **이번 세션 환경에서는 재현되지 않았다** — 다른 세션/환경의 결과를 이번 결과로 보고하지 않는다는 원칙에 따라 명확히 구분.
  - C(조건부 PPA): 엔진 비의존 계약(코드 게이트, `validated_for_ctfm` 임의 true 금지, 비용 커버리지 null 처리)은 코드로 이미 원칙대로 구현돼 있음을 확인, **변경 없음**. C6(실제 엔진 실행 1건 이상)은 B와 동일 사유로 **blocked**.
  - D(마감 검증): 전체 pytest, OpenAPI/schema drift 검사, 대표 API/worker 흐름 모두 위 로그로 확인. 소스 코드 변경 없음(문서 커밋 1건).
- **NeuroSim crash 해결 여부**: **미해결.** 06에서는 크래시 원인 수정을 시도조차 하지 못했다(엔진 자체가 없어서). 이전 기록의 최소 crash 입력 `[[257,1],[1,1]]` 재현 상태에서 진전 없음.
- **실측 D2D/Retention 데이터 연결과 결합 실험 범위**: 위 A3 항목대로 **연결되지 않음**. LTP/LTD 검증(A1~A5, 1020 states)을 IV/D2D/Retention 전체 검증으로 확대 해석하지 말 것.
- **최종 diff와 엔진 버전/hash/출력 coverage**: `git diff 96fb9bc..2b0a830`은 `handoff/02_measurement-fix-and-next-steps.md` 9줄 추가뿐(소스 코드 0줄 변경). 엔진 버전 정보는 WSL 쪽 g++ 13.3.0만 확인됐고, 엔진 바이너리/커밋 해시는 이번 세션에 존재하지 않아 확인 불가.

따라서 테스트 322개 통과와 06의 실제 HTTP 재실행만으로 NeuroSim PPA나 전체 프로젝트 완료를 선언하지 않는다. NeuroSim 최소 crash `[[257,1],[1,1]]`는 여전히 재현만 된 상태이고, PPA 사용자 경로는 여전히 차단 상태다.

## 6. 프론트 05 — 사용자 요청으로 보류

사용자 우려: 입력칸이 복잡하고 선택 비활성화 이유가 불명확하며, LTP/LTD 한 쌍 입력이 어렵게 느껴짐.

05 중간 보고 및 저장 증거:
- 사용자가 실제 파일 선택을 수행한 A1 LTP/LTD 동시 업로드→분석에서 1020 후보 확인.
- combined 가능/common 불가 확인.
- 상태 **2개만** 선택한 검증용 draft 생성:
  - analysis `675270ff-fc82-4c0a-95e9-01af0e89be64`
  - profile `0f43e178-8ca5-4b4b-81c1-a28bc136ebc2`, revision1, draft
- 위 ID는 원본 PC runtime 전용이며 새 환경에 자동 존재하지 않습니다. 전체 1020 상태 profile처럼 사용하지 마세요.
- 발행→시뮬레이터 선택, A3 흐름, 순차 파일 추가, 방향 중복/누락·열 매핑 누락·삭제/재추가 검증은 미완료.
- Measurements/Profiles/payload 화면 정리 코드는 05 중단 시 미수정이며, **06 작업에서도 전혀 수정하지 않았음을 diff로 재확인**.
- Node/Vite 충돌 보고가 있지만 이전 동일 PC에서 빌드 성공 기록도 있음. 사용 Node 실행 경로/버전/의존성부터 재확인하며 환경 전체가 불가능하다고 단정하지 않음.
- Chrome 연결 문제와 웹 코드 결함은 별개. API 업로드를 실제 브라우저 파일 업로드 검증으로 표시하지 않음.

사용자는 지금 프론트보다 백엔드를 우선하므로, 06 상태를 확인(이번 문서에서 완료)한 뒤 UI를 진행합니다. UI 완료 기준은 실제 두 파일 입력→쌍 지정→분석→profile 발행→선택→실행→다운로드이며, 자동 테스트만으로 대체하지 않습니다.

## 7. 팀원의 다음 작업 순서

1. **로컬 최신 브랜치와 06 원본 보고서/증거 전달 확인**. 이 문서 게시와 함께 `claude/adc-order-comparison` 브랜치가 `origin`에 push됐으므로 `git fetch && git log origin/claude/adc-order-comparison` 로 확인. main만 받고 C2C를 다시 구현하지 않기.
2. **NeuroSim 잔여 작업**. 엔진 checkout 확보(경로/획득 방법 확인 필요) → crash 원인 해결 → 실제 입력/차동 처리/ADC·trace 의미 일치 → 비용 블록 계측. 부분 비용은 coverage·missing_components와 함께 제공하고 완전한 총계로 포장하지 않기.
3. **실측 IV/Retention 파서**. `관련 자료/IV Sweep/`의 반복 열 레이아웃과 `관련 자료/Retention/`의 program/erase 이종 time 축을 어떻게 처리할지 소자팀 확인 후 파서 추가. LTP/LTD 검증을 IV/D2D/Retention 전체 검증으로 확대 해석하지 않기. 없는 C2C 데이터는 수동 가정으로 구분.
4. **필드 계약 통일**. `mapping_errors`/`mapping_metrics`, `adc`/`adc_metrics`의 공식 이름을 API·core·UI·schema에서 확정하고 기존 호환(현재 프런트의 `?? ` fallback) 유지.
5. **프론트 환경 복구 및 05 마무리**, 이후 C2C 입력 UI 연결.
6. 최종 API·worker·엔진·브라우저 테스트를 구분해 보고하고 코드 PR 검토/병합.

## 8. 재현 명령과 환경

최신 작업 브랜치 전달 후 해당 checkout에서 실행합니다.

```powershell
git status --short --branch
git log -5 --oneline
.venv/Scripts/python.exe packages/contracts/export_schemas.py --check
.venv/Scripts/python.exe packages/contracts/export_openapi.py --check
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

임시 디렉터리 권한 오류(`PermissionError` on a pytest tmp path)가 나면 `TMPDIR` 환경변수가 접근 불가한 경로를 가리키고 있을 수 있습니다(06에서 실제로 발견된 이 머신 한정 환경 문제). 기존 사용자 디렉터리를 삭제하지 말고 `TMPDIR`을 unset하거나 전용 basetemp를 지정하세요.

API/worker가 실행 중인 **검증용 runtime**에서는(기존 runtime과 분리하려면 별도 `CTFM_STORAGE_ROOT`·포트 사용):
```powershell
.venv/Scripts/python.exe scripts/measured_workflow.py --conditions A1 --compare-adc-orders --adc-bits 6
.venv/Scripts/python.exe scripts/smoke_c2c_workflow.py
```

스크립트는 서버에 분석/profile/experiment를 생성할 수 있습니다. 기존 runtime을 삭제하지 말고 검증용 환경을 구분합니다. 기존 checkpoint 재사용 시 해당 ID와 파일이 실제 존재하는지 확인합니다.

Python은 저장소 lock에 맞춘 환경, 프론트는 package.json 요구에 맞는 Node, AIHWKit/NeuroSim은 검증된 Linux/WSL 환경을 확인합니다. Windows torch 실행 성공을 AIHWKit/NeuroSim 성공으로 보고하지 않습니다.

## 9. 인계 완료 조건

- 팀원이 최신 코드 커밋을 fetch할 수 있음 — **2026-09-23 게시로 충족**: `claude/adc-order-comparison`가 `origin`에 push됨(강제 push 아님, main 미병합).
- 06 원본 보고서와 증거를 읽을 수 있음 — `docs/verification-backend-batch-2026-09-23.md`(팀 공유용 요약, 개인 로컬 경로 제거)로 브랜치에 포함. 원본 `local_report/06_REPORT_backend-batch.md`·`evidence/06/`은 이 저장소 밖(사용자 로컬 `local_report/`)에 있으므로 별도 전달 필요.
- 실제 남은 항목과 실행 환경/명령이 확인됨 — 위 5·7·8절.
- 프론트 미완료 및 수동 모델 가정이 결과에 명시됨 — 위 4·6절.

현재는 **코드 브랜치 + 인수인계 문서 게시 완료** 단계입니다. main으로의 PR/병합, NeuroSim 엔진 확보, 실측 IV/Retention 파서, 05 프론트 마무리는 모두 남아 있습니다.
