> 상태 변경 (2026-09-18): 이 문서는 과거 계획·검토 또는 기술 참고 자료입니다. 구현 기준은 [확정 설계 v1.0.0](spec/README.md)입니다. 본문의 미확정·승인 대기·이전 규칙은 새 명세를 대체하지 않습니다.

# AIHWKit–NeuroSim 통합 조사

조사일: 2026-09-01
범위: IBM AIHWKit과 Georgia Tech NeuroSim 공식 자료만 사용

## 결론

두 도구는 **하나의 로컬 프로젝트와 하나의 실행 파이프라인 안에서 함께 사용할 수 있다.** 다만 둘 다 똑같이 `import`하는 Python 라이브러리는 아니다.

- **AIHWKit**은 `pip install aihwkit` 후 Python에서 직접 import하는 PyTorch 연동 패키지다. 아날로그 레이어, 학습·추론, 소자 비이상성, ADC/DAC 이산화 등을 모델 정확도 계산에 반영한다. [IBM AIHWKit README](https://github.com/IBM/aihwkit#readme)
- **DNN+NeuroSim V1.4**는 공식 Python/PyTorch wrapper와 별도로 컴파일하는 C++ 하드웨어 추정 엔진의 조합이다. 공식 설치법도 `make`로 `Inference_pytorch/NeuroSIM/main`을 만든 뒤 `python inference.py ...`를 실행하도록 안내한다. [NeuroSim V1.4 README](https://github.com/neurosim/NeuroSim/tree/2DInferenceV1.4)
- 따라서 NeuroSim을 일반적인 pip 패키지처럼 `import neurosim`하는 방식으로 전제하면 안 된다. 공식 V1.4 wrapper는 PyTorch forward hook으로 레이어별 weight/input CSV와 shell command를 만들고, 마지막에 C++ 실행 파일을 호출한다. [공식 `hook.py`](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/utee/hook.py), [공식 `inference.py`](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/inference.py)

## 어떤 NeuroSim을 선택해야 하나

공식 중앙 저장소는 용도별 버전을 별도 branch로 제공한다. 현재 프로젝트처럼 **학습이 끝난 모델의 2D CIM 추론 정확도와 하드웨어 성능을 평가**하려면 `2DInferenceV1.4`가 가장 직접적인 후보이다. 이 branch는 1–130 nm 기술 노드, partial-parallel read, XY bus/H-tree 선택을 지원하며 inference용 DNN+NeuroSim으로 분류된다. [NeuroSim 공식 버전 목록](https://github.com/neurosim/NeuroSim#versions-and-key-features)

`2DTrainingV2.1`은 on-chip training 평가용이다. 이번 프로젝트가 디지털 학습 후 R3 기반 **추론**을 평가한다면 우선순위가 낮다. [NeuroSim 공식 버전 목록](https://github.com/neurosim/NeuroSim#versions-and-key-features)

## 역할 분담

| 단계 | 권장 도구 | 담당 결과 |
|---|---|---|
| 모델 학습과 기준 정확도 | PyTorch | 체크포인트, 디지털 정확도 |
| R3 전도도 매핑과 소자 편차 | AIHWKit | 모델별 Monte Carlo 정확도 분포 |
| ADC bit에 따른 정확도 영향 | 우선 AIHWKit | bit별 정확도·포화·양자화 손실 |
| 배열·ADC·주변회로 비용 | NeuroSim V1.4 | 면적, 지연, 동적 에너지, 누설, TOPS/W, throughput |
| 최종 결과 | 프로젝트 orchestrator | 정확도–면적–지연–에너지 종합 비교 |

AIHWKit은 추론 시 programming/drift 계열의 장기 weight noise와 매 MAC마다 달라지는 단기 forward non-ideality를 구분하며, `SinglePairConductanceConverter`로 가중치를 전도도 쌍에 매핑할 수 있다. [AIHWKit hardware-aware inference 문서](https://aihwkit.readthedocs.io/en/latest/hwa_training.html), [conductance converter API](https://aihwkit.readthedocs.io/en/latest/api/aihwkit.inference.converter.conductance.html)

NeuroSim V1.4의 C++ 엔진은 네트워크 구조와 레이어별 weight/input trace를 받아 타일 이용률과 레이어·칩 단위 면적, 지연, 에너지, ADC/누산기/주변회로 breakdown, TOPS/W 등을 표준 출력으로 낸다. [공식 `main.cpp`](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/main.cpp)

따라서 “1·2번은 AIHWKit, 3번은 NeuroSim”이라는 구분은 대체로 맞지만 절대적인 경계는 아니다. **ADC가 정확도에 주는 영향은 AIHWKit**, **그 ADC와 회로가 면적·속도·에너지에 주는 영향은 NeuroSim**으로 나누는 것이 명확하다. NeuroSim 공식 wrapper도 `ADCprecision`, `cellBit`, `onoffratio`, conductance variation 등을 받지만, 두 도구가 서로 다른 가정으로 정확도를 중복 계산하게 두기보다는 역할을 분리하는 편이 결과 해석에 유리하다. [NeuroSim V1.4 `inference.py`](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/inference.py)

## 권장 연결 방식

두 툴의 내부 객체를 직접 결합하지 말고, 프로젝트의 Python 실행기가 아래와 같은 **정규화된 실험 artifact**를 만들고 각 adapter가 이를 읽게 한다.

```text
공통 실험 설정 + 학습된 모델
          |
          +--> AIHWKit adapter --> 정확도/Monte Carlo 결과
          |
          +--> NeuroSim adapter --> 구조 CSV + weight/input traces
                                  --> C++ 실행
                                  --> PPA 결과 파싱
          |
          +--> 통합 결과 JSON --> 프론트엔드
```

공통 artifact에 최소한 다음을 고정해야 한다.

- 모델 ID, 레이어 종류·크기, 체크포인트 hash
- dataset split, 입력 표본 정책, seed
- R3 `Gmin`, `Gmax`, variation 정의와 단위
- weight/activation/cell bit, ADC bit
- subarray 크기, parallel rows, mapping 방식
- 각 파라미터가 실측인지 가정값인지 나타내는 provenance

이 seam이 필요한 이유는 NeuroSim V1.4가 기본적으로 VGG8, DenseNet40, ResNet18용 모델과 `NetWork_*.csv`를 제공하며, 임의 모델을 사용하려면 wrapper의 모델 정의·network CSV·trace 생성 규칙을 맞춰야 하기 때문이다. 공식 hook은 weight와 activation을 CSV로 내보내고 C++ command line에 그 경로를 전달한다. [NeuroSim V1.4 README](https://github.com/neurosim/NeuroSim/tree/2DInferenceV1.4), [공식 `hook.py`](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/utee/hook.py)

## 실무상 주의점

- **Windows 직접 실행보다 WSL2/Linux가 안전하다.** AIHWKit 공식 설치 문서는 Linux/WSL용 conda 설치를 안내하고, NeuroSim V1.4가 공식 검증한 환경도 Red Hat·Ubuntu와 GCC이다. [AIHWKit README 설치 절](https://github.com/IBM/aihwkit#installation), [NeuroSim V1.4 설치 절](https://github.com/neurosim/NeuroSim/tree/2DInferenceV1.4#installation-steps-linux--anacondaminiconda)
- NeuroSim 기본 `Param.cpp`는 기술 노드, memory type, array/ADC 구조, `Ron/Roff`, read voltage 등 많은 회로 가정을 코드에 포함한다. R3 실측치를 넣더라도 나머지를 기본값으로 두면 결과는 “R3 실측만으로 확정된 실제 칩 성능”이 아니라 **가정된 회로 조건에서의 추정치**다. [공식 `Param.cpp`](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/Param.cpp)
- NeuroSim wrapper의 `--onoffratio`, `--vari`, `--ADCprecision`은 Python 정확도 경로에 사용되지만, C++ 회로 추정은 `Param.cpp`의 `resistanceOn`, `resistanceOff`, `levelOutput`, read voltage를 별도로 사용한다. R3의 절대 `Gmin/Gmax`와 ADC 조건을 PPA에도 일치시키려면 이 C++ 설정까지 같은 공통 artifact에서 생성해야 한다. 비율만 맞추고 절대 저항을 기본값으로 두면 R3 기반 전류·에너지 추정이라고 보기 어렵다. [공식 `inference.py`](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/inference.py), [공식 `Param.cpp`](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/Param.cpp)
- NeuroSim V1.4의 C++ 결과는 기본적으로 사람이 읽는 stdout 형식이다. 통합 프로젝트에서는 wrapper가 stdout을 저장·파싱해 자체 JSON schema로 변환하는 편이 좋다. 출력 항목은 공식 `main.cpp`의 summary에 정의돼 있다. [공식 `main.cpp`](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/main.cpp)
- NeuroSim은 비상업적 CC BY-NC 4.0 조건으로 공개되고, AIHWKit은 MIT 라이선스다. 배포·재사용 시 두 라이선스를 별도로 확인해야 한다. [NeuroSim 공식 README](https://github.com/neurosim/NeuroSim#readme), [AIHWKit LICENSE](https://github.com/IBM/aihwkit/blob/master/LICENSE.txt)

## 추천 결정

1. 하나의 Python orchestrator가 전체 실험을 관리한다.
2. AIHWKit은 Python dependency로 설치하고 직접 호출한다.
3. NeuroSim V1.4는 고정 branch의 별도 source dependency로 관리하고 WSL/Linux에서 빌드한다.
4. NeuroSim은 Python `subprocess`로 공식 wrapper 또는 C++ executable을 실행한다.
5. 두 도구 사이에는 Python 객체가 아니라 versioned JSON/CSV artifact를 둔다.
6. 최종 프론트엔드에는 정확도뿐 아니라 NeuroSim의 면적·지연·에너지와 각 값의 실측/가정 구분을 함께 전달한다.
