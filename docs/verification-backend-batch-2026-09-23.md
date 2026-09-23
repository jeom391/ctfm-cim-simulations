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
| NeuroSim 엔진 실행/PPA 실제 계산 | **blocked** | 이번 세션 환경에 엔진 checkout이 없음(아래 참고). 코드의 `validated_for_ctfm` 게이트·비용 커버리지 처리는 이미 원칙대로 구현돼 있음을 확인(변경 없음) |

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

## 3. NeuroSim 상태 (blocked, 세션 환경 문제)

- 저장소에는 NeuroSim 엔진 자체가 들어있지 않다. 실제 엔진은 `CTFM_NEUROSIM_ROOT` 환경변수(기본 `/opt/ctfm-engines/neurosim`)가 가리키는 외부 checkout을 전제로 한다.
- 과거 문서(`docs/implementation-status.md`)에는 WSL Ubuntu 24.04 + g++ 13.3.0으로 특정 커밋을 빌드해 성공했다는 기록이 있으나, **이번 검증 세션의 실제 WSL 환경에는 그 엔진 checkout이 존재하지 않음을 전체 파일시스템 검색으로 확인했다.** 컴파일러 버전(g++ 13.3.0)은 동일하게 설치돼 있어 소스만 확보되면 다시 빌드를 시도할 수 있는 상태다.
- `validated_for_ctfm`을 임의로 true로 바꾸지 않는 게이트, 비용 커버리지가 부분적일 때 `status:"partial"`과 `missing_components`로 표시하고 null 총계를 유지하는 처리는 코드로 이미 구현돼 있음을 확인했다(이번에 변경하지 않음).
- NeuroSim 최소 crash 재현 기록(`[[257,1],[1,1]]`, SIGSEGV)은 과거와 동일하게 미해결 상태다. 이번 세션은 엔진이 없어 원인 조사를 진행하지 못했다.

## 4. 남은 작업

1. 실측 IV/Retention: 위 2절의 레이아웃 문제를 소자팀과 확인 후 파서 추가.
2. NeuroSim: 엔진 checkout 경로/획득 방법 확보 후 crash 원인 조사·최소 패치·회귀, 이어서 조건부 PPA 실제 실행 연결.
3. `mapping_errors`/`adc` 등 결과 필드 공식 이름 통일(API/core/UI/schema), 기존 호환 유지.
4. 05번 프론트 작업(측정 화면 재구성, LTP/LTD 쌍 검증 UI) 재개.
