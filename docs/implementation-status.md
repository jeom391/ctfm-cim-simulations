> **설계 후속 결정 (2026-09-20):** [두 PDF에 대한 답변](implementation-decisions-2026-09-20.md)과 [v1.2 기준](spec/08-hardware-baseline.md)이 추가됐습니다. 아래 실행 기록은 보존하며 새 기준 구현/검증 완료를 뜻하지 않습니다.

## v1.2 기준 구현 (2026-09-20)

[08 기준 명세](spec/08-hardware-baseline.md)와 [PDF 답변](implementation-decisions-2026-09-20.md)의 개발
순서 1~5를 구현했습니다. 이 절은 구현과 자동 검증 범위를 기록하며, 실측 파일 회귀나 엔진 crash
수정 완료를 뜻하지 않습니다.

### 1. 행 번호 인수 조건과 1 ms 취급

- `packages/ctfm-core/tests/test_measured_a1_regression.py`를 개수 검사에서 **행 번호 관계 검사**로
  교체했습니다. 전환 행 j의 읽기 상태는 행 j-2에서 온다는 규칙을 모든 상태에 대해 확인하고,
  명세가 든 예(전환 1024 → 읽기 1022)는 해당 전환이 있을 때 별도로 확인합니다. 1024/1022라는
  **개수**는 파일별 provenance이므로 `CTFM_A1_EXPECTED_TRANSITIONS` /
  `CTFM_A1_EXPECTED_READ_STATES`를 지정했을 때만 단언합니다.
- 같은 작업에서 이 테스트의 기존 결함 두 개를 고쳤습니다: `source_rows`를 분석기에 전달하지
  않았고, 열 매핑을 `columns=`로 넘겨 분석기가 읽지 못했습니다. 실제 A1 파일이 와도 그대로는
  실행되지 않는 상태였습니다. 합성 워크북으로 새 단언이 실제로 동작하는 것을 확인했습니다.
  분석 방향은 `CTFM_A1_DIRECTIONS`로 지정합니다(한 시트가 두 극성을 동시에 담을 수 없음).
- `read_pulse_width_s == 1e-3` 일괄 거부를 제거하고 **출처 검사**로 바꿨습니다
  (`neurosim.read_window_problems`). 쓰기/프로그램 펄스로 표기된 출처, 또는 선언된
  `write_pulse_width_s`와 같은 값은 크기와 무관하게 거부하고, 읽기로 출처가 명시된 1 ms는
  받아들입니다. 출처가 없으면 검사가 불가능하므로 `read_pulse_width_source`를 필수 필드에
  추가했습니다.
- 10 ns 가정 대비 settling/ADC 시간 검사는 `neurosim.schedule_feasibility`로 분리했습니다.
  현재 엔진 요약 출력에는 대응하는 지연 값이 없으므로 결과는 **`not_performed`** 이며
  `feasible`로 표시하지 않습니다.

### 2. 실행 계약 1.2.0

- `schema_version` 1.2.0, `hardware.adc_order` (`subtract_then_adc` 기본 /
  `adc_then_subtract`) 추가. ADC off에서는 order가 null(적용 안 됨)입니다.
- `tile_size`는 ADC 여부와 무관하게 **항상 명시**합니다. 물리 배열 크기이기 때문입니다.
  ADC off에서 null이던 1.1 계약은 유지하지 않습니다.
- 1.1.0 요청은 재해석하지 않고 `schema_migration_required` 오류로 거부합니다. 1.1.0으로 기록된
  결과의 의미는 그대로 보존합니다.
- OpenAPI/JSON Schema/TypeScript를 재생성했고, capabilities는 `hardware.adc_orders`를 노출합니다.

### 3. 정확도 계산 (입력 8 bit · 두 plane · 두 ADC 순서)

- 입력은 unsigned 8 bit, `q=clip(floor(255x/r+0.5),0,255)`, LSB부터 고정 8 cycle bit serial이며
  전부 0인 cycle도 건너뛰지 않습니다. r은 픽셀 1, hidden은 **디지털 checkpoint의 validation 5k
  ReLU 최댓값**이고 bit 수·배열·경과 시간 사이에서 고정됩니다(test 데이터 미사용).
- 가중치는 더 이상 `scale*(G+ - G-)` 단일 행렬로 합쳐 계산하지 않습니다. G+와 G-를 각각 물리
  plane으로 유지하고 tile마다 `p+`, `p-`를 계산합니다. 부분합 단위는 지멘스×입력 bit이며 물리
  전류는 여기에 VDS를 곱한다는 사실을 결과에 기록합니다.
- `subtract_then_adc`는 `p+ - p-`를 `[-R,R]`에서, `adc_then_subtract`는 `p+`, `p-`를 각각
  `[0,R]`에서 양자화한 뒤 차감합니다. 양자화는 **bit plane마다** 수행하고 2^k를 곱해 합산합니다.
- ADC 범위는 nominal M0에서 **ADC를 우회한 경로**로 한 번에 수집하며, 한 번의 패스로 두 순서의
  범위를 모두 얻습니다(순환 보정 없음). 범위는 bit 수·배열·시간점 사이에서 공유합니다.
- 실행 결과에 **D1**(디지털 가중치 + 8 bit 입력)을 추가해 FP32 → 입력 양자화 → 매핑 → ADC 손실을
  분리합니다. D0/D1은 모두 `torch_reference`로 기록됩니다.
- Retention 배율은 두 plane에 공통으로 적용됩니다(기존 `retention_common_gain` 가정 그대로).

검증:
- 손계산 fixture(2입력 1출력, G pair와 bit 입력을 손으로 따라갈 수 있는 값)로 두 순서의 결과를
  확인합니다.
- **ADC off에서 bit serial 합과 8 bit 복원 direct MAC의 일치**를 NumPy와 torch 양쪽에서
  확인합니다(인수 조건 2).
- 3~8 bit × 64/128/256 × 두 순서 = 36개 조합을 `simulation.math`의 독립 NumPy 모델과 대조합니다.
  허용 오차는 임의값이 아니라 ADC 1 LSB가 8 cycle shift-add를 통과한 값입니다.

### 4. 격리 빌드·캐시와 crash 최소 재현

- `ctfm.adapters.neurosim_build`: `levelOutput = 2^adc_bits` 등 Param.cpp 컴파일 타임 상수를
  설정별로 패치하고, **upstream commit + patch hash + resolved config + compiler/version/flags +
  target platform**을 key로 캐시합니다. 빌드는 임시 디렉터리에서 수행한 뒤 단일 rename으로
  등록하고, 같은 key의 동시 빌드는 디렉터리 lock으로 직렬화합니다(오래된 lock은 회수).
  빌드 전 패치된 소스를 **다시 읽어** 요청값과 다르면 실패시킵니다. 원본 checkout은 복사만 하고
  수정하지 않습니다.
- 검증은 가짜 빌드 명령으로 수행하므로 Windows에서도 캐시·lock·원자성·effective 검사가 돌아갑니다.
  실제 컴파일 검증은 엔진 호스트 몫입니다.
- `scripts/linux/repro_neurosim_crash.py`: 보고된 784×128×10에서 시작해 이분법으로 **여전히
  죽는 최소 형상**까지 줄이고, argv·return code·stderr·엔진 identity(commit/binary hash)를
  `repro.json`에 남깁니다. 결정성 확인을 위해 최소 형상을 여러 번 재실행합니다. 출력 10을 96으로
  패딩하거나 모델을 바꾸는 우회는 하지 않습니다. **엔진 호스트에서 실행해야 하며 이 작업에서는
  실행하지 않았습니다.**

### 5. 블록 비용 합산과 coverage

- `neurosim.circuit_inventory`: 논리 R×C 타일이 두 개의 물리 배열을 뜻한다는 전제로 물리 셀 수
  `2·R·C`, plane당 가중치 1 셀(bit slicing 없음), 타일/plane별 ADC 수, 추론당 변환 cycle을
  계산합니다. `adc_then_subtract`는 plane마다 변환기가 필요하고 `subtract_then_adc`는 차감 후
  하나이므로 **같은 bit 수라도 ADC 수가 다릅니다**. 입력 버퍼·최종 누산·연결망·shift-add는 레이어당
  한 번, row driver·column MUX·배열은 plane별로 계산 대상임을 구조로 표시합니다.
- `neurosim.cost_coverage`: 상태는 `partial`이며 총계는 **null**입니다. 누락 블록을 이름으로
  보고합니다 — `analog_subtraction_frontend`, `bipolar_range_conversion`(차감 후 ADC),
  `digital_subtraction`(개별 ADC 후 차감), `differential_plane_pair`(양쪽). 쓰기 datapath와
  시간/배열별 반복 평가는 `excluded_by_scope`로 따로 표시합니다.
- 엔진이 성공적으로 실행되더라도 누락 블록이 있으면 상태는 `partial`이고, 엔진의 칩 총계는
  `engine_totals`에만 남으며 공개 `area/energy/latency`는 null로 유지됩니다.

### 6. 프론트

- 차감 후 ADC / 개별 ADC 후 차감 라디오 선택, 08 §6의 한 줄 설명을 툴팁이 아닌 **항상 보이는
  문구**로 배치했습니다. 같은 bit 수가 같은 비용을 뜻하지 않는다는 문장을 함께 표시합니다.
- 배열 크기는 ADC off에서도 선택·전송됩니다. 입력이 unsigned 8 bit bit-serial 고정이라는 점과
  ADC off가 실물 ADC 제거와 다르다는 점을 명시합니다.
- PPA 패널은 `측정 전도도를 적용한 선형 등가 회로의 조건부 비용 추정` 라벨과 함께 물리 구성
  표, 누락 블록 표, 범위 제외 항목, 엔진 총계(전체 PPA 아님), 읽기 구간 검사 결과를 보여줍니다.
- C2C는 자료·계약 연결 전까지 disabled 그대로입니다.

### 7. 후속 작업 (같은 날, 남은 항목 중 호스트에서 가능한 것)

**Param.cpp 실제 필드명 대조 — 모듈이 틀려 있었습니다.** upstream 2DInferenceV1.4의 `Param.cpp`를
받아 대조한 결과, 생성자는 `param->levelOutput = ...` 가 아니라 **bare 대입**
(`levelOutput = 32;`)을 씁니다. 처음 작성한 정규식은 실제 파일에서 단 하나도 매칭하지 못했을
것입니다. 다음을 수정했습니다.

- 대입 패턴을 문장 시작에 고정하고 `==`를 배제했습니다. `else if (technode == 14)` 같은 비교를
  대입으로 오인하지 않습니다.
- 패치 대상 필드를 실측으로 확정: `operationmode`, `memcelltype`, `accesstype`, `globalBusType`,
  `SARADC`, `currentMode`, `pipeline`, `speedUpDegree`, `temp`, `technode`, `numRowSubArray`,
  `numColSubArray`, `numColMuxed`, `levelOutput`, `cellBit`, `readPulseWidth`.
- **엔진이 파생시키는 값은 패치하지 않습니다**(`DERIVED_FIELDS`): `parallelRead`는
  `operationmode`에서, `numRowParallel`은 `parallelRead`에서, `dumcolshared`는 `levelOutput`에서,
  `readVoltage`는 technode 표에서 결정됩니다. 처음 설계에서 `parallelRead`를 직접 쓰려 했는데
  생성자가 뒤에서 덮어쓰므로 무효였습니다.
- **조건부 재대입 검사**: `cellBit`은 `memcelltype==1`(SRAM)에서 1로 강제되고, `numColMuxed`는
  conventionalSequential+SRAM에서 재대입됩니다. 해당 조건이 이 설정에서 성립하면 패치가 무효가
  되므로 **빌드를 거부**합니다. 조건이 성립하지 않는 설정(우리 baseline: RRAM)만 통과합니다.
  이유 없이 두 번 대입되는 필드도 거부합니다.
- 실제 `Param.cpp` 전문에 대해 16개 필드 전부가 패치→재독 왕복하는 것을 확인했습니다.

**빌드 캐시를 실행 경로에 연결.** `ppa_result`가 실행 전에 `neurosim_build.build()`로 설정별
바이너리를 얻고 `run_engine(binary=...)`로 그것을 실행합니다. 빌드 실패는 `failed` 상태와 사유로
드러나며, 참조 checkout의 바이너리(upstream 상수로 컴파일된 것)로 조용히 되돌아가지 않습니다.
`build_config()`가 admitted preset + 요청 ADC bits를 컴파일 타임 설정으로 옮깁니다
(RRAM→2, CMOS_access→1, MLSA/current→SARADC 0·currentMode 1, XY bus→globalBusType 0,
`adc_bits`→`levelOutput=2^bits`). NeuroSim이 모델링하지 않는 cell/access 종류는 거부합니다.

**차단 사유와 미완 사유를 분리.** 이전에는 `DIFFERENTIAL_PLANE_UNRESOLVED`가 `reasons`에 무조건
들어가서 **엔진 실행 자체가 영원히 막혀** 있었습니다(빌드 연결도 도달 불가 코드였습니다).
이제 두 가지를 구분합니다.

- `blocking_reasons` — preset 미승인, 엔진 미빌드, crash 형상. 실행하지 않습니다.
- `incomplete_reasons` — 비용 모델이 없는 블록. 실행은 정당하고, **총계만 null**로 남습니다.

명세 §5의 "정확도는 제공하고 알려진 블록 비용은 partial, 전체 값은 null"을 그대로 따릅니다.
성공적으로 실행되어도 미완 블록이 있으면 상태는 `partial`이고 엔진 총계는 `engine_totals`에만
남습니다.

**두 plane 비용 합성 규칙 구현** (`compose_differential_cost`). 결정 A5가 규칙을 확정했으므로
규칙 자체는 더 이상 미결이 아닙니다. 남은 것은 블록별 SI 값입니다.

- per-plane 블록(array, row driver, column MUX)은 **두 plane에 걸쳐 합산**, shared 블록(입력 버퍼,
  최종 누산, 연결망, shift-add)은 **한 번만** 계산합니다.
- 지연은 두 plane을 동시에 읽으므로 **max(plane) + 공통 누산·차감 시간**입니다.
- 차감 후 ADC는 변환기가 공유 블록, 개별 ADC 후 차감은 plane별 블록입니다.
- 어느 블록이든 값이 없으면 **이름으로 보고하고 총계는 전부 null**입니다. 0으로 메우지 않습니다.
- 손계산 가능한 블록 값으로 "단일 plane 총계 × 2가 아님", "느린 plane이 지연을 정한다",
  "변환기 하나 차이"를 각각 검증합니다.
- `missing_components`에 `per_block_engine_costs`를 추가했습니다. 합성기는 준비됐고 더할 숫자가
  없다는 뜻입니다.

**입력 인코딩 차이를 수치로 측정** (`activation_trace_fidelity`). NeuroSim의 FC activation trace는
부호 있는 two's complement라서 **음이 아닌 신호는 격자의 양의 절반만** 씁니다. 8 bit trace는
비음수 신호에 대해 128 레벨 = **실효 7 bit**이며, 정확도 경로의 256 레벨과 다릅니다. 레이어마다
실효 레벨 수·실효 bit·unsigned 코드 대비 최대 오차를 측정해 결과에 싣습니다.
`decode_activation_planes()`로 인코더를 역변환해 왕복 오차가 1 LSB 이하임을 확인했습니다.

**검증된 ADC 순서를 capabilities에 노출.** `validated_combinations`가 이제 `adc_order`를
포함합니다. 프론트도 순서까지 대조하므로, 한 순서에서 검증된 bit/tile 조합이 다른 순서에서도
검증된 것처럼 통과하지 않습니다.

**AIHWKit 검증 스크립트를 v1.2 경로로 교체.** `scripts/linux/verify_aihwkit_adc_combinations.py`가
이제 bit-serial + 두 plane + 두 순서를 `differential_linear` 기준과 대조하고, ADC off에서
bit serial == direct MAC도 backend에서 확인합니다(39개 조합). 허용 오차는 ADC 1 LSB가 8 cycle
shift-add를 통과한 값입니다. **이 호스트에는 AIHWKit이 없으므로 같은 코드를 torch_reference로
치환해 39/39 통과만 확인했습니다. AIHWKit 실행은 엔진 호스트 몫입니다.**

검증: Windows `uv run --locked pytest -q` **239 passed, 5 skipped**. 웹 `tsc --noEmit`,
`npm test` 13 passed, `npm run build` 통과.

### 8. 엔진 실측 (2026-09-20, WSL `/opt/ctfm-engines`)

이전 절에서 "엔진 호스트 몫"으로 남겼던 항목을 실제로 실행했습니다. 환경은 2026-09-19에 만든
WSL Ubuntu의 `/opt/ctfm-engines`가 그대로 남아 있었고, NeuroSim 바이너리는 commit
`ac828e6723bf077c9b1423c5c72ff6e4981e90f4`, g++ 13.3.0 빌드입니다.

#### Param.cpp 패치를 실제 빌드 소스로 검증

다운로드본이 아니라 **빌드에 쓰이는 checkout의 Param.cpp**에 대해 16개 필드 전부가 패치→재독
왕복했습니다(불일치 0). 앞 절의 필드명 수정이 실물에서도 맞습니다.

#### 격리 빌드·캐시를 실제 g++로 검증

`neurosim_build.build()`가 실제 checkout을 복사·패치하고 g++로 빌드해 캐시에 원자적으로
등록하는 것을 확인했습니다. 첫 빌드 3.9초, 같은 key 재요청은 `cached=true`로 재사용됩니다.
**ADC bits가 실제로 다른 회로를 만든다는 것을 수치로 확인**했습니다(784×128×10, subArray 256):

| ADC bits | levelOutput | ADC 면적 m² | 칩 면적 m² | 지연 s | 에너지 J |
|---|---|---|---|---|---|
| 3 | 8 | 3.09e-8 | 1.79e-6 | 6.32e-7 | 3.64e-9 |
| 5 | 32 | 6.35e-8 | 2.05e-6 | 6.83e-7 | 5.66e-9 |
| 8 | 256 | 3.77e-7 | 3.88e-6 | 1.61e-6 | 3.62e-8 |

`pipeline=false`로 빌드되므로 layer-by-layer 출력이 나오며, 같은 설정 3회 실행이 완전히
동일했습니다. **이 수치는 22 nm 주변회로 가정 위의 조건부 추정이며 CTFM PPA가 아닙니다.**

#### crash 최소 재현과 — 기록된 규칙이 틀렸습니다

`scripts/linux/repro_neurosim_crash.py`로 784×128×10에서 이분법 축소를 실행했습니다(22회 시도,
최소 형상 `[[257,1],[1,1]]`, SIGSEGV(-11), 3회 재실행 모두 재현). 축소 과정에서
`[[256,128],[128,10]]`이 **완주**하는 것이 드러나 경계를 따로 측정했습니다.

측정 결과(subArray 64, 특별히 표기한 경우 제외):

| 형상 | subArray | 결과 |
|---|---|---|
| 784×128×10 | 64 / 128 | **SIGSEGV** |
| 784×128×10 | **256** | **완주** |
| 257×128×10 | 32 / 64 | SIGSEGV |
| 257×128×10 | 128 | 완주 |
| 256, 255, 196, 128 ×128×10 | 64 | 완주 |
| 260, 320 ×128×10 | 64 | SIGSEGV |
| **512**×128×10 | 64 | **완주** |
| 128×10, 256×10, 1024×10, 256×64 | 64 | 완주 |
| 784×64 | 64 | SIGSEGV |
| 784×128 | 64 | 완주 |

이전 기록의 두 가지 주장이 **직접 측정으로 반증**됐습니다.

1. **"출력 96 미만은 모두 crash"** — 틀렸습니다. `128×10`, `256×10`, `1024×10`, `256×64`는
   subArray 64에서 모두 완주합니다. 코드의 `MIN_SAFE_OUT_FEATURES = 96` 가드는 **실제로 도는
   형상을 거부**하고 있었습니다.
2. **"mnist_mlp_v1은 현재 엔진으로 평가할 수 없다"** — 틀렸습니다. **subArray 256에서 완주합니다.**
   이전 스윕이 이 형상에 대해 64/128만 시도했습니다. 재빌드가 고친 것이 아니라(스톡 바이너리도
   256에서 완주) **배열 크기가 결정 요인**입니다.

crash는 fan_in에 단조롭지도 않습니다(257·260·320 crash, 512 완주, 784 crash). 일반 규칙은
주장하지 않고, 측정된 `(형상, subArray)` 쌍만 `MEASURED_TOPOLOGIES`에 기록했습니다.
`topology_support(layer_dims, sub_array)`는 이제 **측정에서 죽은 쌍만** 거부하고, 측정되지 않은
쌍은 시도하게 둡니다(`run_engine`이 별도 process group이라 SIGSEGV가 worker를 죽이지 않음).

관련해서 **preset의 `sub_array`가 요청 배열 크기와 다르면 차단**하도록 했습니다. 다르면 정확도
실행과 다른 회로의 비용을 매기게 됩니다. 빌드 설정도 요청 `tile_size`를 우선합니다.

#### 실무적 의미

`mnist_mlp_v1`의 PPA는 **배열 256에서 가능**합니다. 남은 차단 요인은 엔진 crash가 아니라
검증된 CTFM preset 부재이며, 미완 비용 블록 때문에 총계는 계속 null입니다. 배열 64와 128은
이 형상에서 여전히 엔진 제약으로 평가 불가입니다.

검증: Windows `uv run --locked pytest -q` **241 passed, 5 skipped**. 웹 13 passed, tsc/build 통과.

### 이 작업의 검증 기록

- Windows Python 3.11.9: `uv run --locked pytest -q` **241 passed, 5 skipped**
  (skip은 모두 원본 A1 파일 미제공). 이전 기준은 159 passed였습니다.
- 합성 A1 워크북으로 행 번호 인수 조건 3건이 실제로 통과하는 것을 확인했습니다.
- 웹: `npx tsc --noEmit` 통과, `npm test` **13 passed**, `npm run build` 통과,
  `npm run generate:api` 재생성.
- Linux/엔진 검증(AIHWKit parity, NeuroSim 빌드·실행, crash 최소 재현)은 이 작업에서 실행하지
  않았습니다. 엔진 호스트에서 `scripts/linux/`의 스크립트로 별도 수행해야 합니다.

# v1.1 구현·검증 상태

2026-09-19 작업. 현재 설계 우선순위는 docs/spec/07-first-release-controls.md →03/04의 변경 부분, 나머지 계산은01/02/03입니다. 설계 문서의 배포 당시 “아직 미구현” 문장은 역사적 상태이며 현재 구현은 이 문서를 확인합니다.

## 구현된 흐름

P0: Python workspace/uv.lock, React/npm lock, API 요청/응답 모델, OpenAPI/JSON Schema/TypeScript 생성, SQLite·파일 저장소·공통 오류.
P1: pulse/IV/MW/D2D/Retention, 원본 행/열·단위·해시 추적, 제외 사유, 명시적 교차 선택.
P2: draft→사용자 검토→발행, 상태 선택·revision·ZIP import/export·hash 검증, 실측 후보 매핑 및 실제 MNIST D0/M0.
P3: lognormal D2D의 고정 seeded array, Retention ratio 및 invalid 외삽, signed loss·유효 분모·배열 통계.
P4: PyTorch 타일/ADC, 선택 가능한18개 조합의 수치 검증, 선택적 AIHWKit ideal adapter와 parity gate, NeuroSim/C2C 미지원 상태.
P5: 한 웹 앱의 세 페이지, 전체 API/worker 연결, 진행률·취소·중단 처리, 다운로드·결과 그래프.

## 검증 방법과 경계

- 손계산·합성 fixture 계산 테스트와 API·storage·실제 subprocess 회귀.
- 실제 HTTP 업로드→분석→검토 발행→실험→artifact 검증.
- 공식 MNIST에서 실제5epoch 학습, checkpoint 재사용과10,000개 평가.
- 독립 브라우저에서 실제 파일 업로드·열/단위 확인·프로필 발행·ADC 요청·결과/그래프 확인.
- 소자 프로필은 모두 합성임을 표시. 디지털 MNIST 정확도는 실제 실행 결과이며 합성 mapped 정확도를 실측 CTFM 성능으로 해석하지 않음.

원본 측정 파일이 없으므로 A1 실측 회귀를 완료했다고 주장하지 않습니다. AIHWKit은 이 Windows 환경에 설치되지 않았고 외부 backend parity를 통과했다고 주장하지 않습니다. 최신1차 범위에서 NeuroSim PPA는 검증된 CTFM 등가 preset 부재로 off이며 dummy 수치를 제공하지 않습니다.

seed는07의 명시적 우선순위에 따라 분할·학습·배열에 반영합니다.03의 고정 seed는 추천 재현값20260917로 유지합니다. 사용자의 다른seed를 상수로 덮어쓰지 않으며 다른 분할checkpoint 재사용을 거부합니다.

원본과runtime 산출물은 Git 제외입니다. 기존 .omc 변경은 보존했습니다. 커밋·push는 수행하지 않았습니다.

## 최종 검증 기록 (2026-09-19)

- Windows Python3.11.9: strict pytest129개 통과(103.74초).
- Ubuntu24.04/WSL Python3.11.15: strict pytest127개 통과(64.28초). 마지막 정수 표현/UUID 경계 수정 직전 기준이며 해당 수정은 Windows 전체129개 및 실제 HTTP 추론으로 재검증.
- 프론트11개 테스트·생성 TypeScript·production build 통과.
- Python4개 wheel/sdist 빌드 및 소스 체크아웃 외부 import 검증.
- 실제 MNIST5epoch D0 테스트 정확도96.45%. 소자 상태는 합성 fixture이며 mapped 정확도를 실측 소자 성능으로 해석하지 않음.
- 실제 브라우저 전체 흐름과 ADC3bit/64타일 checkpoint 재사용 성공. JS 오류/모바일 가로 넘침 없음.
- 독립 검토에서 입력 parser/ZIP/프로필 hash/교차 구간/Retention 출처/worker 종료/정수 표현·UUID 대소문자 문제를 수정하고 회귀 확인.

## 엔진 실제 설치·실행 검증 (2026-09-19, 후속 작업)

이전 기록에서 미완료였던 두 엔진을 실제로 설치·빌드하고 실행했습니다. 전용 Linux 환경은
`/opt/ctfm-engines`(WSL Ubuntu 24.04.1, kernel 5.15.167.4)이며, 이전 `/tmp` 환경처럼 사라지지
않도록 영속 경로를 사용합니다. 재현 스크립트는 `scripts/linux/`에 있습니다.

### AIHWKit — 설치·parity·MNIST E2E 완료

- AIHWKit 1.1.0. 공식 PyPI에 **Windows wheel이 없습니다**(manylinux cp310/cp311, macOS arm64만).
  따라서 정확도 엔진은 Linux에서만 노출됩니다.
- **torch 호환 범위를 실측으로 확정**(`scripts/linux/sweep_torch_abi.sh`):
  2.9.1은 `c10::TensorImpl::decref_pyobject` 미정의로 ImportError, 2.10.0–2.12.0은 정상,
  **2.13.0/2.14.0은 import은 성공하나 C++ 쪽이 텐서 shape을 오독**하여 `set_weights`가 거부됩니다.
  워크스페이스 lock은 2.14.0+cpu이므로 **현재 lock으로는 AIHWKit이 동작하지 않습니다.**
- 동작 중인 Windows 환경(torch 2.14.0+cpu)은 그대로 두고, Linux 엔진 환경만 torch 2.12.0+cpu로
  고정했습니다. import 성공만으로 게이팅하면 2.13+에서 조용히 잘못된 결과가 나오므로
  `engine_capabilities()`의 parity probe 게이팅은 필수입니다.
- 실제 parity: tiny fixture `1.19e-07`, fc1 128x784(batch 256) `4.68e-06`, fc2 10x128 `0.0`
  (atol 1e-5 / rtol 1e-4).
- 실제 MNIST E2E(`scripts/linux/e2e_aihwkit_mnist.py`): 같은 checkpoint/seed/합성 프로필로
  torch_reference와 aihwkit_ideal 정확도가 **완전 일치**. baseline D0 0.9646 / M0 0.9459,
  effects(D2D 2배열+Retention+ADC 6bit/128)에서도 배열별 0.9335 / 0.9291까지 일치.
  D0는 torch_reference, 나머지는 aihwkit_ideal로 provenance에 기록되어 조용한 fallback이 없음을 확인.
- ADC 18개 조합(3~8bit × 64/128/256)을 AIHWKit backend에서 독립 NumPy 기준과 비교해 18/18 통과,
  전 조합 `max_abs_error 0.0`(`scripts/linux/verify_aihwkit_adc_combinations.py`). 이 증거에 근거해
  capabilities의 `validated_combinations`에 aihwkit_ideal을 추가했으며, **해당 프로세스에서 실제로
  available일 때만** 노출됩니다. Windows API/worker에서는 여전히 unavailable로 표시됩니다.
- 수정: `make_linear`의 AIHWKit 분기가 grad를 요구하는 파라미터를 반환해 `inference_mode` 밖
  호출자가 grad 추적 텐서를 받던 문제를 공유 경계에서 해결했습니다(추론 전용 바인딩).

### NeuroSim — 빌드·실행·adapter 완료, CTFM preset은 여전히 부재

- DNN+NeuroSim V1.4, commit `ac828e6723bf077c9b1423c5c72ff6e4981e90f4`(2025-03-09),
  gcc 13.3.0으로 빌드 성공(README 기준은 8.5/9.4). 라이선스는 CC BY-NC 4.0입니다.
- 실제 바이너리 실행과 stdout 파싱 확인. 단일 FC 레이어 784x128에서
  chip_area `7.41e-07 m^2`, pipelined latency `7.94e-07 s`, energy `1.05e-08 J`,
  leakage `3.43e-06 W`를 SI로 파싱했습니다. **이는 NeuroSim 기본값(SRAM, 22 nm) 결과이며
  CTFM PPA가 아닙니다.**
- **엔진 자체 제약을 실측으로 확인**: 이 빌드는 일부 형상에서 `CopyPEArray` 내부 SIGSEGV로 죽습니다.
  확인된 crash: `784x128x10`, `784x128x128`, `1024x10`, `128x10`, 그리고 출력이 96 미만인 모든 레이어
  (out=10은 in=128/256/384/512/640/784 및 subArray 64/128 전부, out=16/24/32/48/64는 in=784에서).
  **[2026-09-20 정정] 이 단락의 규칙은 직접 측정으로 반증됐습니다. `1024x10`/`128x10`/`256x10`은
  subArray 64에서 완주하며, `784x128x10`은 subArray 256에서 완주합니다. 위 절 "8. 엔진 실측"을
  참조하세요.**
  반면 **폭이 균일한 다층 FC는 정상 동작합니다**(1024x128 2층·3층 모두 완주). 일반 규칙은 주장하지
  않으며 `CRASHING_TOPOLOGIES` + `MIN_SAFE_OUT_FEATURES`로 실측된 것만 거부합니다. 목록에 없는 형상은
  실행을 허용합니다 — `run_engine()`이 별도 subprocess로 띄우므로 SIGSEGV는 worker를 죽이지 않고
  음수 return code의 `failed` 상태로 나타납니다.
  결론적으로 **mnist_mlp_v1(784→128→10)은 preset 유무와 무관하게 현재 엔진으로 평가할 수 없습니다.**
  **[2026-09-20 정정] 틀렸습니다. subArray 256에서 완주합니다(스톡 바이너리 포함). 이전 스윕이 이
  형상에 대해 64/128만 시도했습니다.**
- 파서는 두 process 모드를 모두 **실제 엔진 출력으로** 검증했습니다. layer-by-layer 출력은
  `Param.cpp`의 `pipeline = false`로 재빌드해야 나오므로 원본을 건드리지 않고 별도 사본
  (`/opt/ctfm-engines/neurosim-lbl`)을 빌드해 확인했습니다. 두 모드의 실출력이 회귀 테스트 픽스처입니다.
- **상류 예제 smoke 완주**(`scripts/linux/smoke_neurosim_upstream_traces.py`): 상류 VGG8의
  8개 레이어(conv 6 + FC 2) trace를 상류 자신의 hook으로 생성하고, 상류가 만든
  `trace_command.sh`를 그대로 실행해 **return code 0**을 받았습니다. 저장소의 `parse_stdout`이
  파싱한 값은 chip_area `8.44e-05 m^2`, pipelined latency `1.54e-04 s`,
  energy `5.67e-05 J`, leakage `2.41e-03 W`, TOPS 8.02 / TOPS/W 17.70입니다.
  **NeuroSim 기본 SRAM·22 nm 설정이며 CTFM PPA가 아닙니다.**
- 다만 상류 추론 래퍼는 **CPU 전용 호스트를 지원하지 않습니다.** 서로 다른 3곳입니다:
  (1) `inference.py`의 `torch.load(pretrained)`에 `map_location`이 없고 동봉 `VGG8.pth`가 CUDA
  저장, (2) `modules/quantization_cpu_np_infer.py`가 파일명과 달리 5곳에서 `device='cuda'` 하드코딩,
  (3) `utee/wage_quantizer.py`의 `torch.cuda.FloatTensor`. 상류 소스를 수정하지 않고 외부 래퍼에서
  각각 우회했습니다. 이 실행은 `vari=0.0`이라 (2)의 잡음 항이 항등적으로 0이므로 CPU 이동이
  수치를 바꾸지 않습니다.
- `ctfm.adapters.neurosim` 신규: engine 상태 탐지(commit/binary SHA256), NetWork csv 생성,
  weight/activation trace 인코딩, preset gate, 프로세스 그룹 단위 실행·타임아웃·취소,
  exit code 처리, SI 파싱, `model_mismatches`.
- trace 인코더는 상류 `utee.hook` writer와 **바이트 단위 동일**함을 실제 checkout에 대해 검증했습니다
  (`scripts/linux/verify_neurosim_adapter.py`). 파서는 두 process 모드(layer-by-layer/pipelined)를
  라인 전체로 앵커링합니다 — 앵커가 없으면 buffer readLatency를 시스템 지연으로 오독합니다.
- preset gate는 닫힌 상태를 유지합니다. preset 없음, 상류 SRAM 기본값, `validated_for_ctfm` 미표시,
  필수 필드 누락, 1 ms write pulse를 read latency로 재사용하는 경우를 모두 거부하며,
  `area/energy/latency`는 0이 아니라 `null`입니다. `engines.ppa=off`와 `preset_id=null` guard는
  그대로 두었고 완화하지 않았습니다.

### CTFM preset에 필요하지만 측정으로 얻을 수 없는 값

`REQUIRED_PRESET_FIELDS`에 코드로 명시했습니다: technode, read voltage, read pulse width,
cell_bit, synapse_bit, sub_array, parallel_rows, ADC 구조, ADC 공유 열 수, interconnect,
memcell type, 입력 정밀도. 특히 NeuroSim은 readVoltage를 technode 표에서 **내부적으로 결정**하므로
(22 nm → 0.55 V) 측정 VDS=0.1 V를 그대로 대입할 수 없습니다. 또한 NeuroSim은 weight당
`ceil(synapseBit/cellBit)` 컬럼을 쓰고 균일 레벨을 가정하므로, 명세가 요구하는
"plane당 1 analog cell, 2 plane 차동, 비균일 실측 상태"와 구조적으로 다릅니다.
이 차이들은 `MODEL_MISMATCHES`로 항상 결과에 기록됩니다.

### 실제 HTTP 전체 흐름 (Linux, 두 엔진)

`scripts/linux/e2e_http_engines.sh`가 API와 worker를 **같은 venv·같은 `CTFM_STORAGE_ROOT`** 로
기동하고, 업로드→분석→검토 발행→실험→결과까지 두 엔진으로 실행합니다. API가 보고하는 capability는
worker가 실제로 계산하는 환경과 같아야 하므로 스크립트는 서버의 `/capabilities`를 먼저 조회해
요청 엔진이 available인지 확인하고, 아니면 실행하지 않습니다.

결과: checkpoint 공유 True, 정확도 불일치 없음(D0 0.9646), `effective_config.engines.accuracy`가
요청값과 일치, 사용된 엔진은 torch_reference 실행에서 `['torch_reference']`,
aihwkit_ideal 실행에서 `['aihwkit_ideal','torch_reference']`(D0만 디지털이므로 torch_reference).
엔진이 조용히 대체되면 스크립트가 실패하도록 단언했습니다.

### 결과의 PPA 필드

`run['ppa']`와 결과 최상위 `ppa`는 더 이상 하드코딩이 아니라 `ctfm.adapters.neurosim.ppa_result()`
를 거칩니다. 따라서 엔진 빌드 상태(commit/binary hash), preset 판정, 거부 사유 목록,
`model_mismatches`가 결과에 남습니다. `area/energy/latency/raw_output`은 `null`입니다.

### 검증 기록 (엔진 작업 이후)

- Windows strict pytest **150 passed**(기존 129 + NeuroSim adapter 21). 단, 이 호스트에서
  `OSError: [WinError 10014]`(Winsock)로 e2e 1건이 간헐 실패합니다. 인수인계에 기록된 기존 호스트
  문제이며 새 프로세스 재실행으로 150 통과를 확인했습니다. 계산 코드로 우회하지 않았습니다.
- Linux(WSL, torch 2.12.0+cpu, aihwkit 1.1.0 설치 상태) strict pytest **150 passed**.
  이전 기록의 Linux 127개는 낡은 값입니다.
- 웹 11 tests, `npm run generate:api`, production build 통과. OpenAPI/JSON Schema 스냅샷 최신
  (capabilities 변경은 데이터이며 스키마 형태를 바꾸지 않음).

### NeuroSim 엔진 입력 조립기 (2026-09-20 추가)

이전에는 어댑터에 **부품만 있고 조립기가 없어** 프로덕션 경로에서 한 번도 호출되지 않았습니다.
`build_engine_inputs()`로 연결했습니다.

- nominal 매핑 가중치와 trace 앞 256개에서 포착한 레이어별 입력으로 NetWork csv와
  weight/activation trace 일체를 생성합니다. 레이어 입력은 별도 forward를 새로 구현하지 않고
  `Network.__call__`의 `record_inputs`로 공유 지점에서 포착하므로 정확도 경로와 어긋날 수 없습니다.
- NeuroSim이 weight를 `algoWeightMin/Max = -1/+1`로 정규화하므로(Param.cpp 120–121행)
  nominal w_hat을 그 범위로 나누고 **레이어별 divisor를 결과에 기록**합니다.
- `Ron=1/Gmax`, `Roff=1/Gmin`을 발행 프로필의 채택 상태에서 산출해 전달합니다.
- `export_preset()`이 effective preset JSON과 SHA256을 **거부된 실행에서도** 남깁니다.
- 실제 엔진 검증(`scripts/linux/verify_neurosim_adapter.py`): writer_parity / engine_roundtrip /
  preset_gate_closed / **assembled_inputs_accepted** 4개 모두 OK. 조립기 출력을 빌드된 바이너리에
  그대로 넣어 returncode 0, chip_area `7.41e-07 m^2` 파싱, Ron 20 kΩ / Roff 100 kΩ 전달 확인.
  검증 형상은 784×128 단일 레이어입니다(mnist_mlp_v1 전체 형상은 엔진이 죽으므로).
- **차동 2 plane 비용은 모델링하지 않았습니다.** NeuroSim에 두-plane 차동 배열이 없어 명시적 근사가
  필요한데, 이는 물리 판단(결정 A5)이므로 임의로 정하지 않고 `DIFFERENTIAL_PLANE_UNRESOLVED`를
  모든 결과의 `reasons[]`에 남깁니다.
- ADC bits → NeuroSim `levelOutput = 2^bits`는 Param.cpp 컴파일 타임 상수라 재빌드가 필요하며,
  격리 빌드/캐시 설계(결정 C1) 이전에는 반영하지 않습니다.

막힌 항목의 사유는 [구현못한이유.pdf](구현못한이유.pdf), 결정 대기 목록은
[정해야할것.pdf](정해야할것.pdf)에 정리했습니다.

### 아직 하지 않은 것

- 브라우저(headless)에서 AIHWKit 엔진을 선택해 화면까지 확인하는 UI 검증. HTTP 계층은 위와 같이
  검증했고, 웹은 capabilities의 `validated_combinations`를 그대로 사용합니다.
- CTFM 등가 회로 preset의 물리적 타당성 검토. 위 필수 값들에 대한 **사용자 결정이 필요**합니다.
- 원본 A1 실측 파일 회귀(파일 미제공).