> **설계 후속 결정 (2026-09-20):** [두 PDF에 대한 답변](implementation-decisions-2026-09-20.md)과 [v1.2 기준](spec/08-hardware-baseline.md)이 추가됐습니다. 아래 실행 기록은 보존하며 새 기준 구현/검증 완료를 뜻하지 않습니다.

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
  반면 **폭이 균일한 다층 FC는 정상 동작합니다**(1024x128 2층·3층 모두 완주). 일반 규칙은 주장하지
  않으며 `CRASHING_TOPOLOGIES` + `MIN_SAFE_OUT_FEATURES`로 실측된 것만 거부합니다. 목록에 없는 형상은
  실행을 허용합니다 — `run_engine()`이 별도 subprocess로 띄우므로 SIGSEGV는 worker를 죽이지 않고
  음수 return code의 `failed` 상태로 나타납니다.
  결론적으로 **mnist_mlp_v1(784→128→10)은 preset 유무와 무관하게 현재 엔진으로 평가할 수 없습니다.**
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