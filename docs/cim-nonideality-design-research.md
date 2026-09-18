> 상태 변경 (2026-09-18): 이 문서는 과거 계획·검토 또는 기술 참고 자료입니다. 구현 기준은 [확정 설계 v1.0.0](spec/README.md)입니다. 본문의 미확정·승인 대기·이전 규칙은 새 명세를 대체하지 않습니다.

# 실측 전도도 기반 추론·Retention·회로 비이상성 설계 제안

작성일: 2026-09-17. 이 문서는 공식 AIHWKit 1.1.0 문서·소스 및 NeuroSim V1.4 저장소를 확인한 기술 제안이다. 사용자 확정 사항과 추가 모델 가정을 구분한다. 원자료의 실제 구조·수치 검증은 별도 데이터 점검 결과를 따른다.

## 1. 사용자 확정 사항

- D2D는 전도도 편차를 계산하여 시뮬레이터에서 사용한다.
- LTP/LTD는 A열 시간 6초 이상에서 C열의 읽기→펄스 전환 행을 찾아 두 행 앞 B열 전류를 추출한다. A1~A5 LTP/LTD의 VDS는 모두 0.1 V이다.
- 측정 분석은 제공 PPT의 전체 분석 항목을 포함하는 소자팀 보조 도구이다. 시뮬레이터 입력과 동일 범위일 필요가 없다.
- 사용자는 Program Retention을 중심으로 목표 연도에 따른 추론 정확도 변화를 보고자 한다.
- LTP/LTD 통합 사용은 사용자 아이디어이며, 아래 조건·추천은 아직 채택되지 않은 설계 제안이다.

## 2. Vth와 가중치, 전도도의 관계

추론 모델의 학습 가중치 w는 일반적으로 무차원 수이다. 소자는 저장된 상태에 따라 Vth가 달라지고, 고정 읽기 조건에서 그 Vth에 대응하는 전류 Id가 나온다. 따라서 구현상 연결은 **학습 가중치 → 실현 가능한 소자 상태 → 해당 상태의 읽기 전도도 → 연산 전류**이다. Vth 자체를 신경망 가중치와 동일시하지 않는다.

현재 데이터에서는 G_read = Id / 0.1 V를 사용한다. 이는 해당 Gate·Drain 읽기 조건의 유효 전도도이다. 하나의 VDS에서 측정했다고 다른 입력 전압에서도 Id=G×V가 성립한다고 검증된 것은 아니다. 1차 시뮬레이터는 선형 MVM 추상화를 사용한다고 명시하고, 이후 입력을 전압 크기·펄스 폭 중 무엇으로 표현할지 및 실제 I-V 선형 범위를 연결한다. 이는 측정 범위로부터의 설계적 한계이지 확인된 소자 비선형 계수는 아니다.

AIHWKit의 단일 차동쌍 변환은 두 전도도의 차이를 저장된 scale_ratio로 나누어 가중치를 복원한다. 전도도 단위는 µS이다. [공식 conductance converter 소스](https://aihwkit.readthedocs.io/en/latest/_modules/aihwkit/inference/converter/conductance.html)

제안하는 관계는 w_hat = alpha × (G_plus − G_minus)이다. alpha는 최초 매핑 때 정하고 각 보존 시간에서 고정한다. 0 가중치도 두 소자의 전도도가 같은 상태이지 두 물리 소자가 없다는 뜻이 아니다.

## 3. LTP/LTD 통합 풀의 타당한 의미

권장: **통합 후보 저장소 + 출처를 보존한 유한 상태 집합**. 각 항목에 device_id, LTP/LTD 경로, 펄스 번호, 원본 행, G, 읽기 조건을 남긴다. 같은 전도도에 가까워도 다른 경로의 상태를 자동으로 같은 상태라 가정하지 않는다. 도달하려면 어떤 초기화·펄스 경로가 필요한지 알 수 있어야 한다.

1차 비교는 LTP만 / LTD만 / 통합 후보의 세 조건으로 한다. 통합 풀은 두 경로를 선택적으로 프로그래밍할 수 있다는 가정하의 매핑 가능성 평가이다. 여러 소자의 모든 개별 값을 한 가상 소자가 정확히 재현 가능한 레벨로 간주하는 것은 추가 가정이다. 대표 소자 풀 또는 동일 목표 상태의 소자 간 대표값을 기준 풀로 삼고, 다른 소자의 차이는 D2D로 평가하는 구성이 해석하기 쉽다.

원자료 점검 결과 A1은 LTD 약 11.4–115 µS, LTP 약 348–495 µS로 간격이 있으며 A2도 서로 다른 범위이다. 따라서 우선 **A1~A5별로** 통합 후보를 만들고 구간 사이에 가상의 상태를 보간 생성하지 않는다. 6초 이후 전환 전 두 행 규칙으로 검출되는 내부 상태 수는 파일명 512와 다를 수 있으므로 파일명에서 상태 수를 강제하지 않는다. 수치와 임시 파서의 조건은 [자료 확인 기록](measurement-simulation-design-update.md)에 명시한다.

전도도가 비슷한 상태의 개수가 많다고 모두 구분 가능한 비트가 늘어나는 것은 아니다. 현재 단계에는 전체 후보 수와 채택 수를 각각 표시한다. 잡음 폭·재현성 근거 없이 임의로 유효 비트 수를 인증하지 않는다. 같은 측정 편차를 상태 목록의 흩어짐과 추가 D2D/C2C 잡음으로 이중 반영하지 않도록 명목 상태와 변동성의 출처를 분리한다.

매핑 제안: 낮은 전도도 기준 상태 G_ref를 한쪽에 두고, 부호에 따라 다른 쪽의 실제 후보 상태를 가장 가까운 값으로 선택한다. 이후 필요하면 모든 실제 차동쌍 조합 중 오차 최소 조합을 비교한다. 후자는 조합 수가 늘지만 공통 전류·에너지 및 상태 도달 비용도 달라질 수 있다. 두 경우 모두 실제 후보값으로만 양자화하고, 임의의 중간 전도도를 만들지 않는다.

AIHWKit CustomPairConductanceConverter는 후보 점 사이를 numpy.interp로 보간하므로 이름만 보고 유한 상태 매퍼로 쓰면 안 된다. 별도 최근접 상태 선택과 상태 식별자 보존이 필요하다. [공식 구현](https://aihwkit.readthedocs.io/en/latest/_modules/aihwkit/inference/converter/conductance.html)

## 4. Program-only Retention의 실행 가능한 1차 모델

기존 대화에서 확인한 피팅식 I_P(t)=a+b log10(t), 10초 미만 제외를 출발점으로 삼되, 데이터 검증은 별도 기록을 따른다. t_ref는 10초 이상 최초 기준점이며, 사용자 입력 Y년을 elapsed=t_years로 환산하여 t_target=t_ref+elapsed로 정의한다. Y=0은 원래 매핑 상태와 정확히 같아야 한다. 1년의 초 환산 규약을 저장한다.

**제안 A: 정규화 Program 변화율을 모든 사용 상태에 적용하는 시나리오.** r(t)=I_P_fit(t)/I_P_fit(t_ref), G_s(t)=G_s(t_ref)×r(t). 이는 Program 한 상태에서 측정된 상대 변화를 다른 상태도 공유한다고 가정한 것이며, 측정으로 입증된 상태별 Retention 모델이 아니다. Retention의 VDS·Gate 조건이 LTP/LTD와 일치하는지도 확인해야 한다. LTP/LTD의 0.1 V 확인을 Retention에 확대 적용하지 않는다.

Program 데이터만으로 중간 전도도 상태마다 다른 변화율을 알아낼 수는 없다. 따라서 출력 명칭은 'Program 상대 변화율을 적용한 장기 예측 시나리오'로 하고, 다중 상태 Retention을 확보하면 G_s(t)로 대체한다. A1~A5의 Program 곡선을 각각 사용한 결과 범위는 시나리오 차이로 제시할 수 있으나, 5개 소자의 분산을 곧바로 모든 셀의 독립 시간 잡음으로 적용하지 않는다.

[원자료 확인](measurement-simulation-design-update.md)에서는 Program 전류가 10초부터 약 1,000초까지 모두 증가했다. 따라서 'Retention = 전도도 감소'를 선험적으로 넣지 말고 피팅 기울기의 부호를 유지한다. Retention 파일명의 읽기 조건도 프로필에 따라 다를 가능성이 있으므로, 단위가 같다는 이유만으로 LTP/LTD와 같은 상태의 측정이라 간주하지 않는다.

**핵심 식별 한계:** 차동쌍 양쪽에 같은 절대 변화량 d를 더하면 (G_plus+d)−(G_minus+d)=G_plus−G_minus로 상쇄된다. 같은 비율 r을 곱하면 w(t)=r×w(0)이다. 네트워크와 바이어스·활성화·보정에 따라 정확도가 거의 변하지 않을 수 있다. 목표가 '감소량'이어도 감소를 강제하지 않는다. 실제 원인은 상태별 변화 차이, 셀 간 차이, 회로 범위 제한 등일 수 있지만 현재 자료에 없는 계수를 만들어 넣지 않는다.

Erase를 분석 입력에서 사용하지 않아도, 차동쌍의 기준 소자는 물리적으로 존재한다. 기준 소자를 고정한다고 가정하면 별도 '기준 상태 고정' 시나리오이며 그 안정성은 검증되지 않았다. 기본 시나리오에서는 양쪽 사용 상태에 같은 명시적 상대 변화 모델을 적용하는 편이 일관적이다.

약 1,000초 측정에서 연 단위로 가는 결과는 수만 배 이상 시간 외삽이다. 높은 측정 구간 R²가 장기 수명 검증을 뜻하지 않는다. 로그 직선이 음의 전류를 예측하거나 정의한 물리 범위를 벗어나면 그 시간을 모델 유효 범위 밖으로 표시한다. 단순 0 clipping 결과를 확정 수명으로 보고하지 않는다. 보존 중 상태를 원래 유한 상태 풀로 다시 양자화하면 의도하지 않은 재프로그램 효과가 생기므로 그렇게 하지 않는다.

보고할 값: A_digital, A_mapped(0), A_same_hardware(0), A_same_hardware(Y), retention_delta_pp=A_same_hardware(0)−A_same_hardware(Y). 정확도가 증가하면 음수 변화도 그대로 표시한다. 각 시간에는 같은 가상 소자·같은 프로그래밍 realization을 유지하여 보존 영향만 비교한다.

## 5. AIHWKit: 정확도가 왜 달라지는지 분리하는 단계

| 단계 | 추가 요소 | 목적 |
|---|---|---|
| 0 | 원본 디지털 모델 | 기준 정확도 |
| 1 | 실측 유한 상태 차동쌍 매핑, 이상적 연산 | 상태 개수·간격과 매핑 손실 |
| 2 | D2D만, C2C만, 둘 다 각각 | 독립 기여와 상호작용 |
| 3 | Program Retention만 및 단계 2와 결합 | 초기 편차와 시간 변화를 분리 |
| 4 | ADC/DAC 해상도·범위, 배열 분할을 별도 sweep | 회로 정밀도·비용 절충 |
| 5 | 보정된 읽기 잡음·배선 저항 등 | 추가 측정·회로 근거 확보 후 |

각 효과 하나만 추가한 조건과 누적 조건을 모두 보존한다. 결과를 단순 합산하여 총 정확도 감소를 만들지 않는다. 가상 배열 m개와 재프로그램 반복 k회에서 D2D는 배열 내 고정, C2C는 재프로그램 때만 다시 뽑는다. 순전파마다 새 잡음은 읽기 잡음으로 별도 관리한다. 반복 예측에서 데이터 순서·seed·매핑 alpha를 동일하게 유지한다.

AIHWKit IOParameters는 ADC/DAC, 범위, 출력 잡음, IR drop 등을 제공한다. is_perfect=True는 이 순전파 효과를 끄지만 외부 noise_model 등은 끄지 않는다. 기본 out_noise는 0.06이고 해상도도 유한하다. 따라서 '소자만' 조건을 기본 설정 그대로 실행하면 회로 효과가 섞인다. [공식 IOParameters 문서](https://aihwkit.readthedocs.io/en/latest/api/aihwkit.simulator.parameters.io.html)

InferenceRPUConfig는 기본적으로 PCMLikeNoiseModel과 GlobalDriftCompensation을 생성한다. Program Retention을 PCM drift로 자동 치환하거나 실측 D2D/C2C에 PCM 잡음을 중복 가산하면 안 된다. 기본 모델을 명시적으로 대체·비활성화하고 실측 모델만 적용한다. [공식 config 소스](https://aihwkit.readthedocs.io/en/latest/_modules/aihwkit/simulator/configs/configs.html)

실측 모델 구현은 BaseNoiseModel의 전도도별 programming/drift seam을 사용할 수 있다. 또는 외부에서 물리 G_pair를 유지하고 해당 시점의 유효 가중치만 AIHWKit에 공급하되, 내부 재변환으로 유한 상태·물리 전도도가 바뀌지 않는지 확인한다. [공식 BaseNoiseModel](https://aihwkit.readthedocs.io/en/latest/api/aihwkit.inference.noise.base.html)

ADC/DAC는 처음부터 낮은 비트를 고정하지 말고 높은 정밀도→낮은 정밀도 순으로 비교한다. 예시 8/6/4 bit는 탐색 후보이며 실제 회로 사양은 아니다. bit 수뿐 아니라 clipping 비율과 입력·출력 범위를 함께 보고한다. 보정용 데이터는 테스트 정답과 분리한다. 매핑 scale을 각 시간마다 재설정하거나 출력을 자동 정상화하면 Retention 손실이 가려질 수 있다.

기본 Retention 비교는 drift 보정 off, 추가 실험은 보정 on으로 분리한다. AIHWKit의 global drift compensation은 상수 배율로 보상한다. 보정이 물리 시스템에서 무료로 주어지는 것은 아니므로 기준 읽기·회로 비용도 별도 설명한다. [공식 drift compensation](https://aihwkit.readthedocs.io/en/latest/api/aihwkit.inference.compensation.drift.html)

## 6. NeuroSim과 연결할 범위

제안: AIHWKit이 정확도 평가의 기준 경로를 맡고 NeuroSim은 같은 매핑·배열·정밀도 가정의 면적·에너지·지연 추정을 맡는다. 두 엔진에서 같은 오차를 순차 가산하지 않는다. NeuroSim 자체도 정확도 wrapper를 제공하지만 그것은 별도 검증 경로이다. V1.4 공식 예제에는 cellBit, ADCprecision, subArray, onoffratio가 있으며, partial parallel의 Python wrapper는 single-level cell에 한정한다고 명시한다. [공식 NeuroSim 저장소](https://github.com/neurosim/DNN_NeuroSim_V1.4)

공유해야 할 값: physical G 범위, 읽기 VDS, 상태 표현/차동쌍 수, 실제 소자 수, 배열 크기, 동시에 읽는 행 수, 입력·ADC 해상도, 모델 형상 및 활성화 trace. 비균일 실측 상태 목록을 cellBit 하나로 완전히 전달할 수 있다고 가정하지 않는다. native wrapper의 등간격 상태 가정과 다르면 adapter가 필요하거나 비용 추정을 근사로 표시한다. 공정 노드, cell 면적, 배선·기생 값이 없다면 실제 칩 예측 대신 지정한 회로 가정의 비교 결과이다.

정확도 저하 우려는 회로 효과를 무조건 빼거나 비이상성을 임의로 줄여 해결하지 않는다. 원인별 실험을 통해 필요한 ADC 정밀도·배열 크기·허용 변동 폭을 찾고, 그 조건에서의 비용과 정확도를 함께 비교한다.
