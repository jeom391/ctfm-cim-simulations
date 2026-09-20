# 회로 기준의 근거와 개발 보고서 작성 기준

조사일 2026-09-20. 공식 논문 본문과 코드에서 확인한 내용, 프로젝트 설계 추론, 미검증 가정을 구분한다. 논문 PDF를 재배포하지 않고 원문 링크를 제공한다. 구현 명세는 [08](../spec/08-hardware-baseline.md), 작업 지시는 [PDF 답변](../implementation-decisions-2026-09-20.md).

## 출처별 사용 범위

### E1. Charge-trap synaptic device with polycrystalline silicon channel for low power in-memory computing (2024)

[논문 전문](https://pmc.ncbi.nlm.nih.gov/articles/PMC11585655/)

확인: CTF 측정 특성과 NeuroSim을 이용한 평가 사례. 64×64 subarray, ADC 5bit, 8 column/ADC 구성. 이 값을 추천 초기 비교점으로 택한다. 논문은 다른 소자/데이터셋/엔진 버전이다. 논문의 읽기 2V/100ns, 에너지와 정확도를 우리 소자에 이식하지 않는다. 우리 설정의 최적성 또는 구현 검증 근거로 쓰지 않는다.

### E2. NeuroSim Simulator for Compute-in-Memory Hardware Accelerator: Validation and Benchmark (2021)

[논문 전문](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2021.659060/full)

확인: 특정 40nm RRAM macro와 공정 파라미터를 기반으로 회로 모듈과 비용을 비교·보정한다. 배열뿐 아니라 driver/MUX/ADC/누산 등 주변 회로가 필요하다. 우리의 추론: 측정 G만으로 칩 전체 비용을 검증했다고 주장할 수 없으며 가정·coverage·보정 여부를 기록해야 한다. 특정 실리콘 검증의 오차 범위를 CTFM으로 전이하지 않는다.

### E3. NeuroSim V1.5: Improved Software Backbone for Benchmarking Compute-in-Memory Accelerators with Device and Circuit-level Non-idealities (2025 preprint)

[원문](https://arxiv.org/abs/2505.02314), [HTML §II-C/III](https://arxiv.org/html/2505.02314v1)

확인: 입력 표현, bit slicing, behavioral accuracy와 PPA evaluator의 역할을 구분한다. 문서의 PPA 경로는 bitserial 입력을 사용한다. 우리의 추론: 입력8bit와 bit별 ADC/shift-add를 일관되게 구현한다. 8bit는 프로젝트 기준 선택이지 CTFM 최적성에 대한 문헌 결론이 아니다. 논문이 존재한다는 이유로 V1.5 실행 성공이나 현재 crash 해결을 주장하지 않는다.

### E4. 공식 NeuroSim 코드

[통합 저장소](https://github.com/neurosim/NeuroSim), [Param.cpp](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/Param.cpp), [SubArray.cpp](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/SubArray.cpp), [SarADC.cpp](https://github.com/neurosim/NeuroSim/blob/2DInferenceV1.4/Inference_pytorch/NeuroSIM/SarADC.cpp)

확인: CTFM native 분기 없음. RRAM/FeFET 읽기 계산의 공통 경로, CMOS access sizing 검사, ADC sharing, 22nm readVoltage 0.55V, readPulseWidth 10ns, 4F×12F 가정 등이 존재한다. **RRAM 경로 채택은 코드 재사용을 위한 공학적 선택이며 CTFM 물리 동등성의 증명이 아니다.** SAR 보정 코드는 다른 ADC와 전체 CTFM 전압 전이를 검증하지 않는다. 링크는 이동 branch이므로 실제 실행은 commit/patch hash를 별도로 저장한다.

### E5. Toward Software-Equivalent Accuracy on Transformer-Based Deep Neural Networks With Analog Memory Devices (2021)

[논문 전문](https://www.frontiersin.org/journals/computational-neuroscience/articles/10.3389/fncom.2021.675741/full)

확인: G+/G− 차동 conductance pair 사용 사례. 부호 있는 가중치 표현의 근거로 활용한다. PCM의 noise/drift 계수, 회로 비용을 우리 CTFM에 복사하지 않는다. 차동 표현 자체가 ADC 위치·아날로그 차감 비용까지 정해주는 것은 아니다.

## 결정의 성격

| 결정 | 근거 | 보고서에 쓸 한계 |
|---|---|---|
| 64×64/5bit/8열 공유 | E1 사례 및 E4 기능 | 비교 시작점, 최적 설정 아님 |
| 측정 상태 기반 차동 매핑 | 기존 합의, E5 표현 사례 | 실제 임의 상태 기록 재현성은 별도 |
| RRAM access 경로 재사용 | E4 공통 읽기 모델 | CTFM 구조·면적·전압 재현 아님 |
| 22nm/300K와 셀 footprint | E4 + 프로젝트 통제 조건 | 실제 소자 공정/치수 아님 |
| 0.55V/10ns 비용 조건 | E4 baseline | 0.1V 측정 G의 선형 전이는 미검증 |
| 8bit bitserial | E3 구조 + 우리 범위 선택 | 정확도 최적성 미입증, 입력 양자화 영향 별도 보고 |
| 두 ADC 순서 | 동작 비교를 위한 설계 | 같은 bits가 같은 비용을 의미하지 않음 |
| 격리 build/cache | 동시 실행 안전·재현성 | 소프트웨어 판단, 소자 논문 주장 아님 |

## 개발 보고서 권장 구조

1. 목적과 범위: 측정 분석 보조 + 측정 기반 추론 정확도 + 조건부 회로 비용.
2. 입력 자료/출처: 새 측정 revision/hash, 단위/읽기 조건, 제외 데이터. 원본 수치 미확보를 물리적 0으로 해석하지 않기.
3. 결정별 ‘문제 → 대안 → 선택 → 근거 → 구현 → 검증 → 한계’.
4. 두 ADC 흐름과 bitserial 순서를 그림으로 제시. 실제 구현 여부 표시.
5. 검증: 합성 손계산, 실제 파일, 엔진 동작, 정확도 parity, config 재현을 구분. 보고된 테스트 수와 직접 재실행 결과 구분.
6. 결과: FP32/input8bit/mapping/ADC/소자 비이상성 정확도 분해, 여러 seed/array 통계, 비용은 coverage와 가정 포함.
7. 한계: 단일 read point, read voltage 전이, 미측정 intermediate retention, C2C 표본 대표성, 누락 front end, 공정/footprint 가정.

사용 가능한 서술: ‘측정 전도도 상태와 비이상성을 반영한 추론을 평가하고, 명시한 주변회로 및 선형 전도도 가정하에서 연산 구조의 비용을 추정하였다.’

피할 서술: ‘실제 CTFM 칩 성능을 검증했다’, ‘512개 측정 표본은 9bit 셀이다’, ‘NeuroSim 자체가 검증됐으므로 우리 결과도 검증됐다’, ‘모델은 설정만 입력하면 물리적으로 타당하다’.

이번 문서화에서는 새 회로 모델 실행/성능 측정은 수행하지 않았다. 문헌 조사는 회로 기준 선택의 근거이며 구현 인수 시험을 대체하지 않는다.
