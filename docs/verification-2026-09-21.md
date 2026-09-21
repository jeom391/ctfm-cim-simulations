# 웹·API 통합 검증과 AIHWKit·NeuroSim 실제 실행 검증 (2026-09-21)

기준: `codex/fix-measurement-csv` 2f88b0b(CSV 파서 수정) 위의 `verify/web-api-engines` 브랜치. [마무리 계획](completion-plan-2026-09-21.md)의 보고 형식(implemented / tested-* / blocked)을 따릅니다. 데이터는 [최신 LTP/LTD 10개](../data/reference/ltp-ltd-2026-09-21/manifest.json)이며 업로드 시 서버가 계산한 SHA256이 manifest와 일치했습니다.

## 요약

| 항목 | 상태 | 근거 |
|---|---|---|
| 전체 자동 테스트 (Windows) | tested-synthetic + tested-measured | `uv run --locked pytest -q` **264 passed, 5 skipped** (skip은 모두 구판 A1 원본 미제공) |
| OpenAPI / JSON Schema 스냅샷 | tested | `export_openapi.py --check`, `export_schemas.py --check` 모두 current |
| 웹 빌드·테스트 | tested | `npm ci && npm run build` 성공, `npm test` 13/13 |
| 합성 smoke (API+worker) | tested-synthetic | `scripts/smoke_workflow.py` rc=0 |
| 실측 CSV → HTTP 전체 흐름 A1~A5 | **tested-measured** | 아래 1절 |
| 브라우저 업로드→분석→결과·다운로드 | **tested-browser** | 아래 2절 (A3) |
| 브라우저 시뮬레이터 ADC 순서 선택→실행→결과 | **tested-browser** | 아래 2절 |
| AIHWKit probe / ADC 조합 / MNIST 대조 | tested-engine | 아래 3절 |
| 실측 프로필로 torch vs AIHWKit (HTTP, 두 ADC 순서) | **tested-engine + tested-measured** | 아래 3절 |
| NeuroSim adapter 검증 | tested-engine | writer 동일성·실행 파싱·preset gate 닫힘 |
| NeuroSim crash 최소 재현 | tested-engine (재현만, 수정 아님) | `[[257,1],[1,1]]` SIGSEGV 3/3, 기존 기록과 동일 |
| NeuroSim PPA 사용자 경로 (P3/P4) | **blocked** | 검증된 preset 없음, gate 닫힘. 이번 범위 밖 |
| 같은 표본으로 두 ADC 순서 비교 | 미수행 | 순서별로 체크포인트가 달라 정확도 차이를 순서 효과로 해석하지 않음 |

## 이번 검증에서 발견·수정한 결함

1. **worker 결과 export가 실측 데이터에서 수 분간 정지** (`apps/worker/src/ctfm_worker/exports.py`).
   xlsx 작성 루프가 행마다 `sheet[sheet.max_row]`를 호출했고, `max_row`/`max_column`은 모든 셀을 훑으므로
   전체가 O(n²)였습니다. 합성 fixture는 작아서 드러나지 않았고, 실측 LTP+LTD 한 쌍(raw 24,000행)에서는
   분석 1개가 약 5분 걸렸습니다(10:54:51 시작 → 10:59:58 종료, 분석 자체는 0.4초). 행 번호를 직접 세도록
   바꿔 같은 입력의 export가 약 7초가 됐습니다. 문자열 셀을 수식이 아닌 텍스트로 두는 기존 보호는 그대로이며
   기존 테스트가 이를 확인합니다. 회귀 테스트 `test_spreadsheet_export_scales_to_measured_table_size` 추가.
2. **시뮬레이터 결과 표의 mapping/ADC 지표가 항상 "—"** (`apps/web/src/pages/simulator/Simulator.tsx`).
   core는 run에 `mapping_errors`, `adc`를 기록하는데 UI는 명세 04의 이름 `mapping_metrics`, `adc_metrics`만
   읽었습니다. UI에서 두 이름을 모두 읽도록 했습니다. 명세 이름으로 core를 맞출지는 계약 변경이므로
   개발 담당이 결정합니다(현재 OpenAPI에는 두 이름 모두 없음).

## 1. 실측 CSV HTTP 흐름 (Windows, torch_reference)

`scripts/measured_workflow.py` (신규). 실행 중인 API+worker에 대해 조건마다 CSV 업로드 → 해시·preview 시작 행 확인
→ `pulse_states` 분석 → manifest의 후보 수, 첫/끝 `source_row`와 전류 대조 → 프로필 생성·발행 → ZIP export
다운로드를 수행하고, 지정 조건은 MNIST 실험까지 실행합니다.

```sh
uv run --locked python scripts/measured_workflow.py   # 기본: A1~A5, A1만 실험, ADC 6 bit subtract_then_adc
```

| 조건 | 상태 수 | export ZIP bytes | 결과 |
|---|---|---|---|
| A1 | 1020 | 198,152 | manifest 대조 통과, 발행 |
| A2 | 1020 | 198,004 | 〃 |
| A3 | 1020 | 208,241 | 〃 |
| A4 | 1020 | 214,310 | 〃 |
| A5 | 1020 | 230,800 | 〃 |

A1 실험 (tile 64, ADC 6 bit, subtract_then_adc, checkpoint `b4d81aa0-…`): D0 96.45%, D1 96.43%, M0 96.44%, ALL 95.88%.
이 수치는 소프트웨어 경로 검증이며 소자 품질 주장이 아닙니다.

## 2. 브라우저 (Chrome, http://127.0.0.1:8000)

- 측정 분석 › LTP/LTD: `LTP_512_A3_228.csv`, `LTD_512_A3_228.csv`를 파일 입력으로 업로드했습니다. 화면에 "Recognized instrument
  table layout v1", "Instrument metadata rows 1-2 excluded" 경고가 표시됐고, 열(Time / MeasResult1_value / MeasResult2_value)과
  단위(s / A / V)는 직접 지정했습니다. 분석은 완료됐고 후보 1020개, 제외 사유 4건(before_start_time, no_next_transition),
  상태 그래프가 표시됐습니다. 다운로드 파일 8개(plot.png, raw.csv 6.2 MB, states.csv, summary.json 12 MB, tables.xlsx 1.5 MB 등)는
  모두 HTTP 200이었습니다.
- CIM 시뮬레이터: A3 실측 프로필, ADC 5 bit, **개별 ADC 후 차감**, checkpoint 재사용으로 요청 JSON을 확인한 뒤 실행했습니다.
  완료 후 결과 표에 D0 96.45%, D1 96.43%, M0 96.42%, ALL 94.50%가 표시됐고, 수정 후에는 mapping 오차와 ADC 포화·양자화
  지표도 표시됩니다. 화면에 aihwkit_ideal은 "사용 불가"로 나옵니다. Windows에는 AIHWKit wheel이 없기 때문이며 정상 동작입니다.
- UX 관찰(수정 안 함): 분석 결과 "계산 요약"이 state_id 1020개를 포함한 원시 JSON을 그대로 렌더링해 페이지가 무거워집니다.
  제외 사유 목록도 JSON 문자열로 나옵니다.

## 3. Linux 엔진 (WSL2 Ubuntu 24.04, /opt/ctfm-engines)

환경: Python 3.11.16, torch 2.12.0+cpu, AIHWKit 1.1.0, g++ 13.3.0, NeuroSim commit `ac828e67…`, binary sha256 `05102096…`.
엔진 venv는 이 저장소를 editable로 참조하므로 위 브랜치의 코드가 실행됐습니다. 로그: `/opt/ctfm-engines/logs/verify-2026-09-21/`.

| 스크립트 | rc | 결과 |
|---|---|---|
| `probe_aihwkit.py` | 0 | fc1/fc2 parity allclose (max abs err 4.7e-6) |
| `verify_aihwkit_adc_combinations.py` | 0 | 39/39 pass |
| `e2e_aihwkit_mnist.py` | 0 | MATCH |
| `verify_neurosim_adapter.py` | 0 | writer_parity / engine_roundtrip / preset_gate_closed / assembled_inputs_accepted OK |
| `e2e_http_engines.sh` | 0 | 합성 프로필, 공유 checkpoint, 정확도 불일치 없음 → MATCH |
| `repro_neurosim_crash.py` | 0 | 784×128×10 → 최소 `[[257,1],[1,1]]`, rc −11, 3/3 결정적 |

**실측 A1 프로필로 torch vs AIHWKit (HTTP, tile 64, ADC 6 bit):** WSL에서 별도 API+worker(포트 8124)를 띄워
`measured_workflow.py --conditions A1`을 torch_reference로 실행한 뒤, 같은 checkpoint로 aihwkit_ideal을 다시 실행했습니다.

| ADC 순서 | torch M0 / ALL | aihwkit M0 / ALL | checkpoint 공유 |
|---|---|---|---|
| subtract_then_adc | 96.40% / 95.96% | 96.40% / 95.96% | 예 |
| adc_then_subtract | 96.46% / 96.32% | 96.46% / 96.32% | 예 |

두 순서는 서로 다른 checkpoint로 실행했으므로(D0 96.48% vs 96.46%) 위 표를 순서 간 비교로 읽지 않습니다.

## 남은 일 (이번에 하지 않음)

- P2 C2C 수동 입력: 정민 담당(8시 이후).
- P3/P4 NeuroSim 사용자 경로·블록 비용·crash 원인 수정: preset이 없어 PPA gate가 닫혀 있고, crash는 재현만 했습니다.
- 같은 checkpoint·같은 표본으로 두 ADC 순서를 한 실험 안에서 비교하는 경로 확인.
- UI/API 필드 이름(`adc` ↔ `adc_metrics`, `mapping_errors` ↔ `mapping_metrics`)을 계약으로 확정.
