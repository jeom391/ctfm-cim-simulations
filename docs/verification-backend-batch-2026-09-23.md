# 백엔드 일괄 검증 결과 (2026-09-23)

기준: `claude/adc-order-comparison` 브랜치, 시작 HEAD `96fb9bc`(위 handoff 3절 표의 05 항목), 종료 HEAD `2b0a830`. 소스 코드 변경은 **없음** — `handoff/02_measurement-fix-and-next-steps.md` 문서 9줄 추가뿐. 이 문서는 팀 공유용 요약이며, 로컬 절대 경로·개인 PC 관련 정보는 제거했다. 원본 보고서(`local_report/06_REPORT_backend-batch.md`)와 검증 로그(`local_report/evidence/06/`)는 이 저장소 밖(작성자 로컬 소통 폴더)에 있으므로 필요하면 별도로 전달받아야 한다.

## 요약

| 항목 | 상태 | 근거 |
| --- | --- | --- |
| 전체 자동 테스트 | tested | `pytest -q` **322 passed, 5 skipped**(0 error). skip 5건은 모두 원본 A1 워크북(`CTFM_A1_FILE`) 미제공으로 인한 기존 skip |
| OpenAPI / JSON Schema 스냅샷 | tested (로그 미저장) | `export_openapi.py --check` → current, `export_schemas.py --check` → current. 세션 내 종료 코드 0 직접 관측, 별도 로그 파일 없음 — 통과로 확정 표기하되 로그 근거가 없다는 점을 명시 |
| 측정 파이프라인 A1~A5 (업로드→분석→프로필→발행→export) | **tested-measured** | 격리된 API+worker 인스턴스(전용 storage root, 기존 runtime과 분리)로 실제 HTTP 재실행. 5개 조건 모두 1020 states, export 성공 |
| A1 MNIST 대표 실행 | **tested-measured** | 신규 checkpoint 학습 후 D0=0.9651, D1=0.965, M0=0.9641, ALL=0.9578 — 과거 문서 수치와 동일 조건에서 재현(강제 일치 아님) |
| ADC 순서 비교 (동일 profile·checkpoint) | **tested-measured** | `--compare-adc-orders`, 모든 비교 불변식 통과, `accuracy_delta_pp=-0.42` |
| C2C/D2D/Retention 결합 경로(off/CV0/D2D 고정/재기록 변화/예산/입력 거부) | tested-synthetic | 기존 단위 테스트(`test_simulation_experiment.py`, `test_simulation_math.py`)로 커버, 이번 전체 pytest 통과에 포함 |
| C2C 취소 처리 | tested (부분) | worker 단위 테스트로만 커버, C2C와 결합한 통합 테스트는 없음(새로 만들지 않음) |
| export/결과 축 vs 표본 수 일치 | tested-synthetic (부분) | 합성 데이터의 분모 일치 테스트만 존재. 실제 실행에서는 실패 0건이라 "일부 실패 시 분모 감소" 사례를 관측하지 못함 |
| 실측 IV 파일 → 분석 연결 | **blocked** | 원본 파일 존재하나 한 시트에 Vg/Id/Ig 열이 반복되는 계측기 레이아웃이라 기존 파서가 인식하는 형식과 다름 |
| 실측 Retention 파일 → 분석 연결 | **blocked** | program/erase가 서로 다른 time 축을 쓰는 2트랙 구조라 기존 `analyze(kind='retention')`이 기대하는 공유 time_s 형태와 다름 |
| API 결과 필드(`adc`/`mapping_errors`) 계약 | 확인만(변경 없음) | `mapping_errors`는 채워짐, `adc`/`adc_metrics`는 아직 없음. 프런트는 이미 두 이름을 양쪽 다 허용(하위 호환 유지). 공식 이름 통일은 별도 작업으로 남김 — 이번 지시로 이름 변경은 하지 않음 |
| NeuroSim 엔진 실행 | **tested-measured (2026-09-23 정정)** | 06의 "엔진 checkout 없음" 판정은 **틀렸다**. 엔진은 `/opt/ctfm-engines/neurosim`에 문서 기록과 같은 commit `ac828e67…`로 존재하며 `main` 바이너리도 빌드돼 있다. `verify_neurosim_adapter.py` 4개 검사 전부 통과(exit 0) |
| NeuroSim PPA 수치 산출 | **blocked (엔진이 아니라 preset)** | `configs/hardware/ctfm-preset.template.json`의 A1~A7·B1~B6 값이 전부 null이라 gate가 정상적으로 닫혀 있음. 코드의 `validated_for_ctfm` 게이트·비용 커버리지 처리는 이미 원칙대로 구현돼 있음을 확인(변경 없음) |

## 1. 측정 파이프라인 및 대표 실행 (tested-measured)

기존 `scripts/measured_workflow.py`를 이번 배치를 위해 새로 띄운 격리 인스턴스(전용 `CTFM_STORAGE_ROOT`, 별도 포트)에 대해 실행했다. 기존에 실행 중이던 다른 runtime과는 분리된 환경이며, 검증 후 이 인스턴스는 정지했다.

- A1~A5 전 조건: 업로드 → 분석(1020 states) → 프로필 발행 → ZIP export, 5개 조건 모두 성공(exit 0).
- A1 조건 MNIST 실험: 신규 checkpoint로 학습 후 D0=0.9651, D1=0.965, M0=0.9641, ALL=0.9578. 과거 `01_REPORT_adc-order-comparison.md`에 기록된 것과 동일한 조건·동일한 수치로 재현됨(체크포인트는 새로 학습된 것이며 값 자체를 강제로 맞추지 않았다).
- A1 조건 ADC 순서 비교: 동일 profile revision·checkpoint에서 `adc_order`만 바꾼 두 실행을 비교, 모든 비교 불변식(동일 profile revision, 동일 checkpoint id/weights, ADC 순서와 그 파생 calibration 외 유효설정 동일) 통과. `accuracy_delta_pp = -0.42`. 이는 단일 조건·단일 checkpoint 비교이며 일반적인 ADC 순서 우열로 발표하지 않는다.

## 2. 실측 IV/Retention 연결이 막힌 이유 (blocked)

실측 IV/Retention 원본 파일은 실제로 존재한다(공유 저장소 밖의 별도 자료 폴더). 그러나:

- **IV**: 한 시트 안에 `Vg/Id/Ig` 3개 열이 여러 번(동일 헤더 반복) 옆으로 이어 붙은 계측기 export 레이아웃이다. 현재 파서(`ctfm.measurement.parse_table`)가 인식하는 유일한 다중-테이블 레이아웃은 LTP/LTD에 쓰인 `Time/MeasResult1_value/MeasResult2_value` 시그니처뿐이라, 이 레이아웃에서는 열 이름 중복으로 "Column labels must be nonempty and unique" 오류가 정상적으로 발생한다.
- **Retention**: `Erase_..._time/전류`, `Programing_..._time/전류`처럼 program과 erase가 서로 다른 time 축을 쓰는 구조라, `analyze(kind='retention')`이 기대하는 공유 `time_s` 전제와 다르다.
- C2C 측정 파서에 적용된 것과 동일한 원칙("형식 미확정이므로 만들지 않는다")을 적용해 새 레이아웃 인식/열 선택 로직을 만들지 않았다. 소자팀 확인 없이 반복된 열 중 하나를 임의로 골라 연결하면 근거 없는 매핑이 되기 때문이다.

## 3. NeuroSim 상태 — 2026-09-23 정정: 엔진은 있다, 막힌 것은 preset이다

06 보고서의 "이번 세션 환경에 엔진 checkout이 없다"는 판정은 **틀렸다**. 같은 날 직접 확인한 실제 상태:

- `/opt/ctfm-engines/neurosim`이 존재하고 `git rev-parse HEAD`가 문서 기록과 같은
  `ac828e6723bf077c9b1423c5c72ff6e4981e90f4`다. `Inference_pytorch/NeuroSIM/main` 바이너리도 빌드돼
  있고, 격리 빌드 캐시(`/opt/ctfm-engines/cache`)에 설정별 엔트리 4개가 남아 있다. g++ 13.3.0.
- `scripts/linux/verify_neurosim_adapter.py`를 실제 엔진에 대해 재실행해 **exit 0**, 4개 검사 전부
  통과: `writer_parity` / `engine_roundtrip`(실제 엔진 stdout 파싱) / `preset_gate_closed` /
  `assembled_inputs_accepted`.
- `scripts/linux/smoke_neurosim_binary.py --sub-array 256 --parallel-read 256`으로 `mnist_mlp_v1`
  (784×128×10)을 **실제로 완주**시켰다(returncode 0, ChipArea 1.16514e-06 m², TOPS 0.300019).
  이 수치는 NeuroSim 스톡 Param.cpp(SRAM·22 nm) 기본값이며 **CTFM PPA가 아니다.**
- 즉 "엔진을 다시 구해야 한다"는 후속 작업 항목은 **해소됐다**. 06 보고서의 전체 파일시스템 검색이
  왜 못 찾았는지는 확인하지 못했으므로 그 판정 방법을 그대로 재사용하지 않는다.

**남은 진짜 차단 요인은 preset이다.** `ctfm.adapters.neurosim.REQUIRED_PRESET_FIELDS`의 14개 값과
`configs/hardware/ctfm-preset.template.json`의 결정 항목(A1~A7 · B1~B6)이 전부 `null`이고
`validated_for_ctfm`이 false라 gate가 **설계대로** 닫혀 있다. 이 값들은 CTFM 등가 회로에 대한 소자팀
결정(technode, memcell 모델 대응, cell geometry, cell/synapse bit, ADC 구조, columns_per_adc,
interconnect, read pulse width와 그 출처)이므로 임의로 채우면 근거 없는 PPA 숫자가 된다. 채우지 않았다.

- `validated_for_ctfm`을 임의로 true로 바꾸지 않는 게이트, 비용 커버리지가 부분적일 때 `partial`
  상태와 `missing_components`로 표시하고 null 총계를 유지하는 처리는 코드로 이미 구현돼 있음을
  확인했다(이번에 변경하지 않음).
- 차동 2 plane 비용 미모델링(`incomplete_reasons`)은 preset과 별개로 여전히 남아 있다.
- crash는 형상이 아니라 (형상, subArray) 쌍의 문제다. `mnist_mlp_v1`은 subArray 64·128에서 SIGSEGV,
  **256에서 완주**하며 이는 `MEASURED_TOPOLOGIES`에 이미 기록돼 있다. 최소 재현 `[[257,1],[1,1]]`의
  상류 원인 조사는 여전히 미착수이나 `mnist_mlp_v1` PPA의 차단 요인은 아니다.

## 4. 남은 작업

1. 실측 IV/Retention: 위 2절의 레이아웃 문제를 소자팀과 확인 후 파서 추가.
2. NeuroSim: 엔진은 확보돼 있으므로(위 3절) **preset 값 확정이 유일한 차단 요인**이다. 소자팀에서 A1~A7·B1~B6를 받아 `configs/hardware/ctfm-preset.template.json`을 채우고 `validated_for_ctfm`을 근거와 함께 올린 뒤 subArray 256에서 실제 PPA 1건을 실행한다. 차동 2 plane 비용 근사는 별도 승인이 필요하며 그때까지 총계는 null로 둔다.
3. `mapping_errors`/`adc` 등 결과 필드 공식 이름 통일(API/core/UI/schema), 기존 호환 유지.
4. 05번 프론트 작업 중 **C2C 웹 입력과 측정 화면 개선(LTP/LTD 쌍 표시, 열·단위 추정, 차단 사유 표시)은 2026-09-23에 완료**했다 — [기록](c2c-web-input-2026-09-23.md). 남은 것은 순차 파일 추가, 방향 중복/누락 검증, 삭제/재추가 흐름이다.
