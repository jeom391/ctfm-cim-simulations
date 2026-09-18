# NeuroSim 사용자 입력·선택 항목 검토

조사일: 2026-09-18. 공식 NeuroSim 2DInferenceV1.4 코드/README를 검토했다. 실제 CTFM adapter 실행이나 회로 보정 완료를 뜻하지 않는다.

## 확정된 UI 방향

사용자가 ADC·배열·회로 조건을 선택하고 실행 요청에 포함한다. 이전 3~8 bit, 64/128/256 배열은 추천 비교 preset이며 고정된 유일 설정이 아니다. 화면에 표시만 하고 엔진에는 기본값을 사용하는 구현은 금지한다. capabilities가 실제 지원 조합과 정확도/PPA 반영 범위를 알려준다. 확인되지 않은 옵션은 experimental/unsupported로 분리한다.

## 추천 추가 항목 (우선순위 제안)

| 단계 | 사용자 설정 | 예상 반영 | 구현 조건 |
|---|---|---|---|
| 기본 | ADC on/off, bit 선택·비교 목록 | 정확도, PPA 활성화 시 ADC 비용 | 기존 quantizer와 C++ levelOutput=2^bits 동기화 |
| 기본 | subarray 크기 선택·비교 목록 | 분할/부분합 양자화, 면적·지연·에너지 | 논리 타일과 물리 배열 차동 plane 대응 검증 |
| 기본 | ADC 출력 범위: 검증셋 자동 calibration 또는 명시 범위 | clip/양자화 정확도 | 명시 범위는 레이어별 effective MAC 단위, 물리 ADC 전류 범위와 구분. API 확장 필요 |
| 고급 | ADC 방식 SAR 또는 MLSA | 회로 비용 | 같은 bits/range의 이상 양자화에서는 정확도 차이를 강제하지 않음 |
| 고급 | ADC당 공유 column 수 | ADC 수와 면적·스케줄 지연·에너지 | numColMuxed 대응, 지원 조합 검증 |
| 고급 | 공정 노드 | 주변회로 PPA | CTFM 소자 실측 공정이 자동 변경되는 것으로 설명하지 않음 |
| 후속 | 동시 읽기 row 수 | 부분합 ADC와 누산, PPA | multi-level partial read 제한과 별도 adapter 검증 필요 |
| 후속 | XY bus/H-tree, buffer 종류, pipeline | PPA | 정확도를 자동 낮추는 효과 아님 |
| 후속 | 입력/활성화 정밀도 | 정확도 및 입력 인코딩 비용 | 동일 activation trace, input encoding과 ADC 순서의 별도 명세 필요 |

기본/고급 구분은 제품 추천이며 새 필드를 이미 구현한 것으로 간주하지 않는다. 공식 Param.cpp에 SARADC/currentMode/numColMuxed/technode/globalBusType/buffer/pipeline 설정이 있다. Python wrapper의 ADCprecision만 바꿔 C++ 설정까지 일치한다고 가정하면 안 된다.

근거: [Param.cpp](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/Param.cpp), [inference.py](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/inference.py), [hook.py](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/utee/hook.py).

## 추가할 가치가 있는 결과

총 PPA뿐 아니라 ADC/누산기/배열/주변회로/배선의 비용 breakdown을 보여준다. 고전도도 소자나 ADC 선택이 어디에 비용을 만드는지 구분할 수 있다. 동일 checkpoint/profile 조건에서 accuracy–energy, accuracy–latency, accuracy–area 비교를 제공한다. 파이프라인의 per-image interval을 end-to-end latency와 혼동하지 않는다. 엔진이 제공하는 지표 의미를 보존한다.

근거: [main.cpp 출력](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/main.cpp), [SubArray.cpp 구성](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/SubArray.cpp).

## 기존 설계에서 정정할 사항

1. upstream 기본 memcelltype은 SRAM이다. 원본 default export만으로 CTFM preset을 만들 수 없다. native 선택 SRAM/RRAM/FeFET 중 CTFM이 없으므로 topology와 equivalent-cell 가정을 먼저 정의한다. FeFET를 같은 트랜지스터라는 이유만으로 물리적으로 동일시하지 않는다.
2. V1.4 readVoltage는 ADC 모델 가정 때문에 노드별 값으로 설정되어 있다. 측정의 VDS=0.1 V는 유지하되 그것을 C++에 대입하기만 하면 유효한 PPA가 된다고 하지 않는다. measurement_vds_v와 engine_read_voltage_v를 구분하고, 보정/모델 전이 근거가 없는 CTFM PPA preset은 지원 완료로 공개하지 않는다.
3. 실측의 불규칙 상태 수를 cellBit=ceil(log2(N))로 바꾸면 같은 weight mapping이라는 보장이 없다. 실제 nominal G pair를 보존하는 adapter와 물리 cell 수 대응이 필요하다.
4. README 및 wrapper는 multi-level cell의 partial parallel 정확도 경로를 제한한다. C++ 파라미터 존재가 우리 end-to-end 연동 지원을 뜻하지 않는다.
5. 연구 목적 CTFM 읽기 전압·G는 프로필에서 가져온다. GUI에서 자유롭게 전압을 바꿔 측정 전도도를 그대로 적용하는 기능은 v1에서 제공하지 않는다.

근거: [Param.cpp](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/Param.cpp), [README partial parallel 제한](https://github.com/neurosim/NeuroSim/tree/2DInferenceV1.4), [wrapper 조건 검사](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/inference.py).

## 설정 전달 구현 원칙

프론트 선택 → 서버 검증 → immutable resolved config/hash → 정확도 adapter와 PPA adapter → 각 adapter의 effective config 회수·대조 → 결과와 함께 저장한다. 사용자 요청값과 effective 값이 다르면 실패 또는 명시적 unsupported로 처리한다. 공용 소스 Param.cpp를 작업마다 덮어쓰지 않고 격리 build/cache 또는 런타임 설정 로더로 동시 실행을 보호한다. 캐시 key에는 code/config hash를 포함한다.

PPA-only 조건 변경은 기존 정확도를 재사용할 수 있으나 재사용 사실과 공통 설정 hash를 표시한다. 하드웨어 범위 비교 중 D2D realization/모델/split을 통제한다. 새로운 옵션의 정확도 모델까지 구현하지 않았다면 해당 옵션은 PPA-only로 표시한다. unsupported 조합을 조용히 clamp하지 않는다.

추가 노드 제한: 공식 main.cpp는 RRAM memcelltype=2와 technode<=14 조합을 거부한다. 1 nm까지 지원한다는 README를 CTFM 등가 아날로그 경로에 그대로 확대하지 않는다. [main.cpp 조건 검사](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/main.cpp).
