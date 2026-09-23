# Linux 가속기 엔진 환경

AIHWKit(정확도)과 NeuroSim(PPA)은 Linux에서만 동작합니다. 이 디렉터리의 스크립트는 전용 환경을
`/opt/ctfm-engines`에 구성하고 검증합니다. 이전 세션의 `/tmp` 환경이 사라진 적이 있어 영속 경로를
사용합니다. `CTFM_ENGINE_ROOT`로 위치를 바꿀 수 있습니다.

Windows workspace(`uv.lock`, torch 2.14.0+cpu)는 이 환경과 분리돼 있으며 변경하지 않습니다.

## 확인된 환경

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04.1 LTS (WSL2, kernel 5.15.167.4) |
| Python | 3.11.16 (uv 관리) |
| torch | 2.12.0+cpu |
| AIHWKit | 1.1.0 |
| NeuroSim | DNN+NeuroSim V1.4, commit `ac828e6723bf077c9b1423c5c72ff6e4981e90f4` |
| compiler | g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) |

## 스크립트

| 파일 | 역할 |
|---|---|
| `setup_aihwkit.sh` | uv 설치, Python 3.11 venv, torch 2.12 + AIHWKit 1.1.0 |
| `sweep_torch_abi.sh` | AIHWKit이 실제로 동작하는 torch 범위를 round-trip으로 측정 |
| `probe_aihwkit.py` | 저장소 probe + mnist_mlp_v1 레이어 크기 parity |
| `verify_aihwkit_adc_combinations.py` | ADC 18조합을 독립 NumPy 기준과 대조 |
| `e2e_aihwkit_mnist.py` | 실제 MNIST를 두 엔진으로 실행해 정확도 대조 (`--effects`로 D2D/Retention/ADC 포함) |
| `smoke_neurosim_binary.py` | 빌드된 NeuroSim 바이너리를 직접 실행 |
| `smoke_neurosim_upstream_traces.py` | 상류 VGG8 예제의 trace를 받아 상류 명령으로 엔진 실행 |
| `verify_neurosim_adapter.py` | writer 동일성 · 실제 실행 파싱 · preset gate 폐쇄 확인 |
| `e2e_http_engines.sh` | API+worker를 같은 환경으로 띄워 전체 HTTP 흐름을 두 엔진으로 실행 |

## 반드시 알아야 할 제약

**AIHWKit은 torch 2.13 이상에서 조용히 깨집니다.** import은 성공하지만 C++ 확장이 텐서 shape을
오독해 `set_weights`가 거부됩니다. 측정 결과:

| torch | 결과 |
|---|---|
| 2.9.1 | ImportError — `c10::TensorImpl::decref_pyobject` 미정의 |
| 2.10.0 / 2.11.0 / 2.12.0 | 정상 |
| 2.13.0 / 2.14.0 | import 성공, `Invalid weights dimensions` |

따라서 가용성 판정은 import이 아니라 `engine_capabilities()`의 parity probe여야 합니다.
`sweep_torch_abi.sh`로 언제든 재확인할 수 있습니다.

**NeuroSim V1.4의 crash는 형상이 아니라 (형상, subArray) 쌍에 달려 있습니다.** `CopyPEArray`
내부 SIGSEGV가 실제로 관측된 쌍만 `ctfm.adapters.neurosim.MEASURED_TOPOLOGIES`에 기록합니다.
`mnist_mlp_v1`(784×128×10)은 subArray 64·128에서 죽지만 **256에서는 완주**하고, 257·260·320은
subArray 64에서 죽는 반면 512는 완주합니다. crash는 fan_in에 단조롭지 않습니다.

이 문서의 이전 판에 있던 두 문장은 2026-09-20 직접 측정으로 **반증됐습니다**(근거:
`docs/implementation-status.md` 8절).

- ~~"출력이 96 미만인 모든 레이어가 crash"~~ — `128×10`, `256×10`, `1024×10`, `256×64`는
  subArray 64에서 모두 완주합니다.
- ~~"mnist_mlp_v1은 현재 엔진으로 평가할 수 없다"~~ — subArray 256에서 완주합니다.

따라서 일반 규칙은 주장하지 않습니다. `topology_support()`는 **측정에서 죽은 쌍만** 거부하고
측정되지 않은 쌍은 시도하게 둡니다. `run_engine()`이 별도 process group의 subprocess로 띄우므로
crash는 worker를 죽이지 않고 음수 return code의 `failed`로 보고됩니다.

**layer-by-layer 출력은 재빌드가 필요합니다.** `Param.cpp`의 `pipeline = true`가 기본이라 기본
빌드는 Pipelined Process 수치만 냅니다. 파서의 layer-by-layer 경로는 `pipeline = false`로 빌드한
사본(`/opt/ctfm-engines/neurosim-lbl`)의 실제 출력으로 검증했습니다.

**상류 추론 래퍼는 CPU 전용 호스트를 지원하지 않습니다.** 서로 다른 3곳을 외부 래퍼에서
우회합니다(상류 소스는 수정하지 않음):

1. `inference.py`의 `torch.load(pretrained)`에 `map_location` 없음 + 동봉 `VGG8.pth`가 CUDA 저장
2. `modules/quantization_cpu_np_infer.py`가 파일명과 달리 5곳에서 `device='cuda'` 하드코딩
3. `utee/wage_quantizer.py`의 `torch.cuda.FloatTensor`

2번은 `torch.normal(0., torch.full(size, vari))`이고 이 실행은 `vari=0.0`이라 항등적으로 0이므로
CPU로 옮겨도 수치가 바뀌지 않습니다. 첫 forward pass는 CPU에서 느리므로 예산은
`CTFM_TRACE_BUDGET_S`로 조절합니다(8개 레이어 완주에 약 1~2시간).

이 smoke는 상류 VGG8 8개 레이어 trace를 상류 hook으로 만들고 상류가 생성한 `trace_command.sh`를
그대로 실행해 rc=0을 확인했습니다. 파싱은 어댑터의 `parse_stdout`을 그대로 사용합니다.

**PPA는 여전히 off입니다.** 엔진이 빌드되고 실행된다는 사실과 CTFM 등가 회로 preset이 검증됐다는
사실은 별개입니다. 검증된 preset이 없으므로 gate는 닫혀 있고 수치는 `null`입니다.
필요한 물리값 목록은 `ctfm.adapters.neurosim.REQUIRED_PRESET_FIELDS`에 있습니다.

## 라이선스

NeuroSim은 Creative Commons Attribution-NonCommercial 4.0 (CC BY-NC 4.0)입니다.
체크아웃은 `/opt/ctfm-engines/neurosim`에 두며 이 저장소에 포함하지 않습니다.
