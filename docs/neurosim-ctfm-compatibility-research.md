# NeuroSim V1.4와 CTFM 측정 상태의 호환성 검토

확인일: 2026-09-18. 대상: 공식 `neurosim/DNN_NeuroSim_V1.4` main의 소스와 README. 이 문서는 조사 기록이며 실행 검증 또는 회로 검증 완료를 뜻하지 않는다. 최종 adapter 개발에서는 upstream commit을 고정해야 한다.

## 확인된 기능과 제약

| 항목 | 공식 구현에서 확인한 내용 | 이 프로젝트에 대한 판단 |
|---|---|---|
| 셀 종류 | `memcelltype`은 SRAM, RRAM, FeFET 분기다. CTFM 분기는 없다. | FeFET를 선택했다고 CTFM 회로가 되는 것이 아니다. 등가 전도도 기반 PPA proxy임을 표시하고 셀 면적·접근 구조의 가정을 별도로 보존해야 한다. |
| ADC | `SARADC`로 SAR/MLSA, MLSA는 `currentMode`로 전류/전압 감지 선택. `levelOutput`은 출력 level 수, `numColMuxed`는 ADC를 공유하는 열 수다. | 사용자 선택 후보로 적합하나 두 엔진 간 ADC 위치·변환 횟수 대응 검증이 먼저 필요하다. |
| 읽기 전압 | `Param.cpp`는 ADC 모델 가정을 이유로 노드별 `readVoltage`를 지정한다. 22 nm는 0.55 V다. | 측정의 0.1 V를 무조건 덮어쓰지 않는다. 측정 읽기 전압과 PPA 내부 전압을 구분하며, 전압을 바꾸는 실험에는 모델 검증이 필요하다. |

근거: [Param.cpp](https://github.com/neurosim/DNN_NeuroSim_V1.4/blob/main/Inference_pytorch/NeuroSIM/Param.cpp), 특히 60–67, 98–101, 242–252, 331–359행. 표의 프로젝트 판단은 코드로부터의 설계 추론이다.

- **SAR 전압 보정은 전체 검증이 아니다.** `SarADC::GetColumnPower`는 0.5 V 조건의 경험식에 맞춰 열 저항을 재조정한다. 이 경로가 있다는 사실만으로 0.1 V CTFM/모든 ADC의 유효성이 확보되는 것은 아니다. [SarADC.cpp 155–160행](https://github.com/neurosim/DNN_NeuroSim_V1.4/blob/main/Inference_pytorch/NeuroSIM/SarADC.cpp#L155)
- **미세 공정 지원은 셀 종류에 따라 제한된다.** 현재 C++ 진입점은 RRAM에서 14 nm 이하를 거부한다. 같은 노드 범위에서는 HP roadmap과 300 K 이외 온도도 거부한다. 웹 선택값 검증에서 동일 제약을 적용해야 한다. [main.cpp 82–99행](https://github.com/neurosim/DNN_NeuroSim_V1.4/blob/main/Inference_pytorch/NeuroSIM/main.cpp#L82)
- **부분 병렬 읽기 지원은 공식 Python wrapper 기준 single-level cell에 한정된다.** 다중 상태 CTFM에서 동시 읽기 행 수를 임의 변경하는 연동은 별도 확장·검증 대상이다. C++ 변수가 있다는 이유만으로 end-to-end 지원이라고 보고하면 안 된다. [공식 README](https://github.com/neurosim/DNN_NeuroSim_V1.4#2-add-partial-parallel-mode-in-python-wrapper-for-single-level-cells-only-and-c-code-for-hardware-estimation)

## 실측 상태와 기본 wrapper의 차이

공식 Python 계산은 `cellRange = 2**cellBit`, 정수 bit-slice, on/off 비에 따른 선형 전도도 변환을 사용한다. 입력도 bit 단위로 나누고, 일부 경로는 데이터 열과 기준 dummy 열을 각각 ADC 양자화한 후 뺀다. 따라서 비균일 실측 전도도 목록과 `Gplus-Gminus` 두 물리 소자를 직접 사용하는 우리 매핑을 그대로 구현한다고 볼 수 없다. [quantization_cpu_np_infer.py](https://github.com/neurosim/DNN_NeuroSim_V1.4/blob/main/Inference_pytorch/modules/quantization_cpu_np_infer.py), 특히 230–268행.

프로젝트 권고:

1. `ceil(log2(측정 표본 수))`를 검증된 셀 bit 수로 간주하지 않는다. 중복 표본, 불균일 간격, 기록 재현성은 별개다.
2. 우리 정확도 계산의 실측 상태 목록은 유지하고, PPA adapter가 실제 물리 열 수·차동 두 경로·입력 bit 수·ADC 변환 수를 명시적으로 전달하도록 한다.
3. 측정 전도도를 균일 상태로 재양자화하는 proxy라면 정확도 경로와 다른 모델임을 출력에 표시한다. 이를 동일 배열의 정확도/PPA라고 합쳐 보고하지 않는다.
4. 차동 합산 후 ADC와 각각 ADC 후 디지털 차감은 다른 구조다. UI 선택과 정확도/PPA adapter가 동일 구조를 사용해야 한다.

이는 기능 확인에서 도출한 권고이며 이 adapter는 아직 실행 검증하지 않았다. C++ 열 저항 계산은 입력 activity, 셀 전도도, 접근·배선 저항을 이용하므로 전도도와 입력 trace의 전달 경로를 검증할 수 있다. [ProcessingUnit.cpp의 GetColumnResistance](https://github.com/neurosim/DNN_NeuroSim_V1.4/blob/main/Inference_pytorch/NeuroSIM/ProcessingUnit.cpp#L676)

## 활용할 출력 및 주변 회로

공식 출력에는 chip/array/ADC/누산/주변 회로 면적, 레이어 및 전체 읽기 지연·동적 에너지·누설, 버퍼·연결망 내역, TOPS/W·TOPS·FPS 등이 있다. 파이프라인의 per-image cycle과 비파이프라인 지연은 구분해서 보여야 한다. 보고된 ADC 항목도 SRAM에서는 sense amp/precharge를 포함하므로 셀 종류에 따라 라벨을 바꿔야 한다. [main.cpp의 결과 출력](https://github.com/neurosim/DNN_NeuroSim_V1.4/blob/main/Inference_pytorch/NeuroSIM/main.cpp#L463)

연결망은 H-tree/XY bus, 전역 버퍼, 누산기, 활성화·pooling 모듈을 포함한다. 먼저 ADC 정밀도·공유 열 수·배열 크기를 비교하고, 이후 버퍼·연결망·pipeline을 고급 선택으로 추가하는 편이 해석하기 쉽다. [Chip.cpp](https://github.com/neurosim/DNN_NeuroSim_V1.4/blob/main/Inference_pytorch/NeuroSIM/Chip.cpp#L66)

공식 매뉴얼 위치는 [User Manual of DNN simulator_V1.4_v3_updated_1229.pdf](https://github.com/neurosim/DNN_NeuroSim_V1.4/blob/main/Documents/User%20Manual%20of%20DNN%20simulator_V1.4_v3_updated_1229.pdf)다. 이번 하위 조사에서는 PDF 본문을 도구로 읽지 못했으며 위 결론은 직접 열람한 코드와 README에 한정한다.
