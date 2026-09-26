# 남은 실측 연결과 NeuroSim 조건부 PPA (2026-09-26, 작업 10)

기준: `claude/adc-order-comparison`, 작업 09 종료 HEAD `fad99de` 이후. 완료된 실측 C2C 설계([결정](c2c-detrending-decision-2026-09-26.md))는 바꾸지 않았다. 증거 파일은 `local_report/evidence/10/`에 있다(원본 측정 파일·배열은 없음).

## 1. 기능별 상태

| 기능 | 상태 | 근거 |
| --- | --- | --- |
| A3 LTP/LTD + A3 Retention(R3(1)) + 두 소자 D2D → 프로파일 발행·export | tested-measured | `scripts/measured_integration_workflow.py`, `integration-A3-retention-d2d-c2c.json` |
| 같은 checkpoint에서 Retention year 0 / 1 / 10 | tested-measured | year 0은 참조(비율 1, `extrapolated=false`), year 1·10은 측정 범위(10~1000 s) 밖이라 `extrapolated=true` |
| **같은 조건** A3 프로파일 + A3 실측 C2C(Program 0.04777 %) | tested-measured | 09의 A1 프로파일 + A3 분석(교차 조건)과 다른 실행 |
| D2D 두 소자 선택 → 분석 → 프로파일 연결 | tested-measured(API) + tested-browser(분석까지) | 아래 3절 |
| IV A5 #225 비정형 블록 | tested-measured | 4절 |
| `engines.ppa=assumed_proxy` 요청·API·worker·UI 게이트 | implemented + tested-synthetic + tested-browser | 5절 |
| mnist_mlp_v1의 NeuroSim 실제 비용 실행 | tile 64 partial (작업 11에서 엔진 결함 수정), 128/256은 엔진 제약으로 거부 | [엔진 수정 문서](neurosim-engine-fix-2026-09-26.md) — 임의 대체 없음 |
| 엔진 배선 확인(합성 768→512→64, tile 64) | tested-measured (합성) | `neurosim-wiring-check-synthetic-*.json` — CTFM·MNIST 수치 아님 |

## 2. Retention·프로파일·추론 (A3)

- 상태 분석(1020 candidate, 네 풀 모두 사용 가능) + Retention 분석(원본 Raw Data의 독립 Erase/Program 시간축, `time_axes=per_direction`, 적합 n=100, R²(Program) 0.9984)을 프로파일에 연결해 발행했다. 프로파일 export(211 KB)는 해시를 검증한다.
- `ProfileManifest.retention`이 `time_axes`를 거부해 발행이 422로 실패했던 결함을 고쳤다(`profiles/__init__.py`, `device-profile.schema.json` 재생성).
- year 0을 측정 범위 밖이라고 표시하던 결함을 고쳤다(`simulation/math.py`): 적합 하한이 10.0004 s처럼 10 s 직후에서 시작해 참조 시점(10 s)이 “외삽”으로 표시됐다. year 0은 참조 그 자체(비율 1)이므로 외삽이 아니다. year > 0만 범위 판정한다.
- 경고 문구 유지: 외삽은 “측정 장기 정확도가 아닌 민감도 시나리오”, 자동 이득 보정 없음. 읽기 바이어스 전이 가정(펄스 상태 VGS=0 V에 Retention 0.5 V 적용) 경고도 유지.

## 3. D2D 두 소자 (UI 포함)

- 측정 화면 D2D 탭에서 파일 두 개(소자 227·228)를 추가 → “같은 파일로 데이터셋 추가”로 소자별 Program/Erase 4개 데이터셋 → 블록 #14(15 V)·구간·분기·단위를 직접 선택 → 확인 → 분석 시작. 결과 CV 0.5187161479819836은 API 실행과 자릿수까지 같다.
- 소자 ID와 데이터셋의 짝이 틀리면(첫 시도에서 실제로 발생) 서버가 `Duplicate measurement dataset or physical-device input`으로 거부한다.
- **연구용 소자 쌍은 선택하지 않았다.** 227/228은 개발 검증용 쌍이며 UI(D2D 탭)와 산출물에 그렇게 표시한다. 남은 입력: 연구에 쓸 소자 쌍(또는 개수)을 장치 팀/연구자가 정해야 한다. 두 소자만으로는 분포 형태를 식별할 수 없다(lognormal 가정 경고 유지).
- 이 쌍의 CV가 매우 크다(0.52). 해당 D2D 실행 정확도(0.45~0.52)는 개발 검증 결과이며 연구 결과가 아니다.

## 4. IV A5 #225

- 12번째 블록 뒤 헤더가 `Id, Ig`(Vg 열 이름 없음)로 어긋난 파일이다. 원본은 수정하지 않았다. 열 의미를 추측하지 않고 **그 블록(열 C36–C37)만 사용 불가**로 표시하고 이유를 반환한다. 나머지 13개 블록은 사용 가능하다(Vth 표와의 일치는 강제하지 않음).
- `scripts/verify_measured_layouts.py`: IV 50개 전부 읽힘(이전 49), Retention 5개 전부 읽힘. 결과 `measured-layouts-inventory.json`.

## 5. NeuroSim `assumed_proxy`

> **작업 11 정정:** 아래 “측정된 한계”의 4×subArray 규칙 설명은 틀렸다. 실제로는 서로 다른 두 원인(타일 분할 결함 + novel-mapping 계층 제약)이며 결함은 격리 엔진에서 고쳤다. mnist_mlp_v1은 이제 tile 64에서 실행된다. [NeuroSim 엔진 수정](neurosim-engine-fix-2026-09-26.md)을 보라.

- 엔진: 공식 저장소(`neurosim/DNN_NeuroSim_V1.4`) commit `ac828e6723bf077c9b1423c5c72ff6e4981e90f4`(CC BY-NC 4.0)를 `~/ctfm-engines/neurosim`(HOME 하위 신규 격리 경로, 기존 설치 없음)에 받아 빌드했다.
- 요청: `schema_version=1.4.0`, `engines.ppa: off|assumed_proxy`(1.2.0/1.3.0은 off 고정), ADC on 필수, `preset_id`는 요청 입력이 아님. 서버는 spec 08 값으로 고정된 preset(`adapters/proxy_preset.py`, 필드별 근거 `basis`)을 쓴다. 결과는 `model_status=assumed_proxy`, `validated_for_ctfm=false`, 한국어 라벨을 항상 싣고 stock SRAM 수치를 CTFM 수치로 표시하지 않는다.
- 게이트: 미빌드 엔진 → 422 `unavailable_engine`, 지원 안 되는 배열 → 422 `unsupported_ppa_configuration`(사유 포함), ADC off → 422. capabilities는 `hardware.ppa_tile_sizes` / `ppa_unsupported`(크기별 사유)를 노출하고 UI는 그것으로 체크박스를 비활성화한다.
- 결과 구조(구현): 유효 config·preset 해시·build 정보·`coverage`(물리 셀 수·ADC 수·변환 cycle, 누락 블록)·`schedule_check`. 누락 블록이 있으면 `partial`이고 `area/energy/latency`는 null(`engine_totals`에만 엔진 값).
- **측정된 한계(핵심):** spec 08 §5는 가중치당 물리 column 1개(bit slicing 금지)를 요구한다. 이 조건에서 이 빌드는
  - mnist_mlp_v1(784×128×10)을 64/128/256 어느 배열 크기로도 실행하지 못한다(`neurosim-proxy-tile-probe.json`, 종료 코드 -11). 엔진은 “SubArray Size is too large … chip hierarchy”를 출력하고 종료한다(`Chip.cpp ChipFloorPlan`: 가장 넓은 층의 물리 column 수(128)를 2의 거듭제곱으로 올린 값 ≥ 4×subArray 필요 → subArray ≤ 32).
  - 이 층 규칙을 만족해도 `CopyPEArray`에서 SIGSEGV가 나는 경우가 있다: 합성 768→512→64는 tile 64에서 **완료**(`engine_totals` 획득, 상태 `partial`)하지만 tile 128, 그리고 784→512→10(행 수가 PE 크기의 배수가 아님)은 tile 64에서 SIGSEGV. 즉 행이 PE 분할과 맞지 않는 경우의 엔진 결함이다(gdb 백트레이스: `TileCalculatePerformance → CopyPEArray`).
  - 이전 문서의 “256에서 실행됨”은 stock **SRAM·비트 슬라이싱(가중치당 8 column)** 설정의 관측이며 spec 08 회로가 아니다. 그 설정은 사용하지 않는다.
- 따라서 mnist_mlp_v1의 실제 PPA 수치는 없다. 요청 시 크기별 사유와 함께 422로 거부한다(자동 대체 없음). 배선(빌드 캐시·엔진 실행·파서·partial 규칙)은 합성 형상 하나로만 확인했다.
- 빌드 캐시는 `CTFM_NEUROSIM_CACHE`, 없으면 `$CTFM_ENGINE_ROOT/cache`(기본 `/opt/ctfm-engines/cache`)를 쓴다. 이전에는 `/opt`가 고정이라 사용자 설치에서 PermissionError였다.

### 열린 결정 (사용자/연구자)
1. mnist_mlp_v1 비용을 원하면: (a) 엔진 hierarchy 검사·`CopyPEArray` 결함을 고친 NeuroSim 사본 사용(엔진 수정은 승인 필요), (b) 더 넓고 PE 분할과 맞는 모델 형상, (c) 가중치당 다중 column(spec §5와 충돌 — spec 변경 필요) 중 선택.
2. 연구용 D2D 소자 쌍.

## 6. 검증 (한 번에)
- Python 전체 pytest, 계약 drift(`export_openapi.py --check`, `export_schemas.py --check`), 웹 `tsc --noEmit`·테스트 33개·`vite build`(WSL). 명령과 결과는 `local_report/10_REPORT_remaining-integration-and-ppa.md`에 있다.
- 브라우저는 내장 패널이고 파일은 JS로 만든 FileList 주입(네이티브 파일 대화상자 아님)이다. 이 환경에서 스크린샷은 빈 화면이라 텍스트/DOM으로 확인했다.
