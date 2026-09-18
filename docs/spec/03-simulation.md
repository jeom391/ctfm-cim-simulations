# CIM 시뮬레이션 명세

버전 `1.0.0` · [개발 시작](README.md)

## 기준 모델과 데이터

MNIST 공식 train 60,000을 seed 20260917로 train 55,000/validation 5,000으로 분리하고 공식 test 10,000을 유지한다. MLP 784→128→10, hidden ReLU, 픽셀 /255, digital bias, Adam lr=0.001, batch=256, 5 epochs, 마지막 epoch 체크포인트를 기본으로 고정한다. seed 하나는 기준 실험이며 여러 학습 seed에 대한 일반화 결과로 표현하지 않는다. 모델 선택 API는 registry 구조로 하되 v1 지원 모델은 이 MLP다. CNN·사용자 임의 모델·hardware-aware retraining은 후속 범위다.

모든 조건은 동일 checkpoint와 split을 사용한다. 검증셋만 calibration과 후보 선택에 사용한다. 테스트 정확도로 풀·매핑·스케일·ADC 범위를 재선택하지 않는다. 학습 환경·결정성 설정·패키지 버전·코드/데이터/체크포인트 SHA256을 저장한다.

## 매핑

기본 `pool=combined`, `mapping=fixed_reference`. 비교 후보 순서는 combined, ltp, ltd, common이며 각 풀에서 fixed_reference, pair_search 순서다. unavailable 풀은 reason을 갖는 skipped 결과다. 초기 평가에서 모든 유효 후보를 보고하고 검증 정확도 최대를 프로필별 추천으로 표시한다. 동률은 위 고정 순서다. 비이상성 실험은 선택한 풀·매핑을 고정하고 효과마다 재선택하지 않는다.

레이어별 `W=max(abs(w))`, `D=Gmax-Gmin`, `scale=W/D`, `w_hat=scale*(Gplus-Gminus)`다. scale은 이후 시간·편차 실험에서도 고정한다. W=0이면 양쪽 Gmin, scale=0을 사용한다. bias는 디지털 원값으로 유지한다.

- fixed_reference: 양수는 Gminus=Gmin, Gplus를 Gmin+abs(w)/scale에 가장 가까운 실측 값으로 선택한다. 음수는 반대다. 0은 양쪽 Gmin이다. 동률은 작은 G를 선택한다.
- pair_search: 목표 차이에 가장 가까운 실제 두 상태 조합을 선택한다. 동률은 Gplus+Gminus가 작은 쌍, 이어 원본 후보 정렬 순서다. 부호는 쌍을 교환한다.
- 측정에 없는 중간 상태 생성·분수 pulse 명령·MW 기반 범위 확대는 금지한다. 소자 두 개에 각 선택 경로로 상태를 독립 기록할 수 있다는 가정을 결과에 남긴다.

Gplus/Gminus 전체 배열과 state_id, 방향, 경로, scale, 레이어별 MAE/RMSE/max error를 저장한다. 서로 다른 실측 수치 개수를 검증된 bit precision으로 해석하지 않는다.

## 물리 해석과 기본 연산

저장 전하/Vth가 고정 읽기점의 ID를 결정하고, 측정 ID/0.1 V를 유효 G로 사용한다. 선형 MAC 근사에서 입력에 따른 개별 전류가 곱셈, 합산 전류가 가중합에 대응한다. ADC/스케일 복원/디지털 bias 후 ReLU를 적용한다. 실제 Gate 진폭 입력의 선형성을 검증했다는 뜻이 아니다. 첫 구현은 이 근사 아래의 추론 평가다.

## D2D

유효 cv=c인 경우 평균 1, 상대 표준편차 c의 양수 lognormal 배율을 사용한다. `s=sqrt(log(1+c*c))`, `factor=exp(-s*s/2+s*z)`, `z~N(0,1)`. 이는 Gaussian 음수 전도도 clipping을 피하기 위한 **설계 분포 가정**이다. c=0인 유효 실측값은 factor=1, 미제공 null은 사용 불가로 구분한다.

기본 가상 배열 m=30, 각 배열에서 물리 소자별 factor를 한 번 뽑아 고정한다. Gplus/Gminus는 서로 독립 소자이며 소자 간·상태 간 상관은 측정되지 않았다. 동일 가상 소자의 배율은 Retention 시간점 전체에서 유지한다. `n_reprogram=1` 고정, C2C=미반영. seed는 루트 seed와 profile revision·array index·layer·polarity로 결정하고 효과 on/off나 시간값에 의존하지 않는다. 각 seed key는 [root_seed, profile_hash, array_index, layer_name, polarity]의 공백 없는 UTF-8 JSON 배열이며 SHA256 digest 앞 8 byte를 big-endian uint64로 해석한다. NumPy Generator(PCG64(seed))의 standard_normal을 row-major 순서로 생성한다. 이 규칙과 NumPy 버전을 manifest에 기록한다.

`G_d2d=G_nominal*factor`. 관측 Gmin/Gmax는 물리 한계가 아니므로 편차 후 그 범위로 clipping하지 않는다. 범위 밖 비율과 최소/최대는 진단으로 출력한다. IV에서 추정한 cv를 모든 pulse 상태에 옮긴다는 가정을 명시한다.

## Retention

Program fit만 추론에 사용한다. `t_ref=10 s`, `t_target=10+years*365.25*86400`, `r(t)=I_fit(t)/I_fit(10)`, `G(t)=G_d2d*r(t)`. years는 유한한 0 이상, years=0이면 r=1이다. 여러 years를 지정하면 0을 자동 포함해 같은 매핑·배열로 평가한다.

고정한 매핑/scale/ADC 범위를 시간마다 재설정하지 않는다. 자동 gain/drift 보정은 끈다. 양쪽 소자에 동일 비율을 적용하므로 공통 이득 변화 시나리오이며 상태별 기억 손실 모델이 아니다. LTP/LTD의 ms 읽기 G를 10초 기준 상태로 간주하고, A3/A4/A5는 읽기 VGS 차이도 전이한다. 각각 별도 assumption ID로 노출한다.

실측 시간 범위를 넘으면 `extrapolated=true`; n년 값은 장기 실측 정확도가 아니라 외삽 민감도 결과로 표시한다. 기준/목표 fit 전류나 배율이 비양수·비유한이면 해당 시간점은 invalid로 처리하며 임의 clipping하지 않는다. 유한하지만 큰 양의 외삽은 값과 범위 경고를 공개한다. 정확도 증가도 그대로 보고한다.

## 사용자 선택과 추천 실험

ADC bits와 tile_size는 사용자 입력/선택값이다. 아래 H1/H2 수치는 시작용 비교 preset이며 고정 조건이 아니다. 단일 조건 또는 사용자가 선택한 조건 목록으로 실행한다. 지원 값/조합은 capabilities로 공개하고 모든 adapter의 effective config에 요청값이 실제 반영됐는지 검증한다. 추가 회로 선택 항목은 [검토 문서](../neurosim-user-controls-review.md)의 제안이며 지원 검증 전 활성화하지 않는다.

| ID | 효과 | 반복 |
|---|---|---|
| D0 | 디지털 원본 | 1 |
| M0 | 실측 유한 상태 매핑 | 1 |
| D1 | M0+D2D | m=30 |
| R1 | M0+Program Retention | 선택 years, 동일 상태 |
| H1 | M0+ADC | bits=3,4,5,6,7,8, 타일 128×128 |
| H2 | M0+타일/ADC | 타일 64/128/256 정사각, ADC 8 bit |
| ALL | 사용자가 선택한 효과 조합 | D2D 사용 시 m=30 |

ALL 기본 추천은 D2D+Retention이며 회로 옵션은 별도 활성화한다. 효과를 모두 켜야 한다는 요구는 없다. 독립 손실을 더해서 ALL 정확도를 만들지 않고 실제로 재추론한다. 노이즈·IR drop·비선형 I-V·C2C·endurance·기본 PCM drift는 v1에서 미반영이다.

## ADC와 타일 계약

effects.adc가 켜진 H 또는 ALL 실험에서 사용자 선택 타일링/ADC 조건을 적용한다. 타일 크기는 논리적 weight 행/열의 최대값이며 차동 구현은 두 physical array plane을 필요로 한다. 레이어 입력 차원은 row 방향으로 나누고 각 부분합을 ADC 후 디지털 합산한다. 다음 레이어 입력과 bias는 digital float다. DAC는 ideal로 유지한다.

기본 정확도 모델은 차동 부분합을 먼저 계산한 뒤 bipolar ADC를 적용하는 이상적 구조다. 검증셋 전체의 명목 M0 타일 출력에서 레이어별 `B=max(abs(partial_sum))`를 구하고 같은 레이어 타일들에 공유한다. B=0이면 zero 출력으로 처리한다. 타일 크기별 calibration은 각각 수행하되 같은 크기의 모든 ADC bit·D2D·시간 실험에서는 B를 고정한다.

`levels=2^bits`, `u=clip(y,-B,B)`, `q=floor((u+B)*(levels-1)/(2*B)+0.5)`, `yq=-B+2*B*q/(levels-1)`로 정의한다. ADC 전 |y|>B 비율을 포화율로 보고한다. 양자화 오차와 clip 손실을 구분한다. 이 bipolar grid는 정확한 0을 포함하지 않을 수 있으며 모델 정의로 기록한다.

AIHWKit adapter는 이상 forward와 명시적 타일/ADC wrapper로 위 계약을 구현한다. 엔진의 내장 quantizer를 사용하려면 같은 grid·범위·rounding의 parity를 먼저 검증한다. 소자 편차는 Gplus/Gminus에 한 번만 적용하고 복원한 weight를 설정한다. 기본 converter의 연속 보간, 기본 programming noise, PCM noise, drift, compensation, forward noise는 사용하지 않는다. 설정값·버전과 효과별 소유 모듈을 manifest에 남겨 이중 반영을 막는다.

## NeuroSim

NeuroSim `2DInferenceV1.4` 계열을 Linux worker에서 빌드하고 실제 commit SHA와 compiler를 pin한다. AIHWKit 버전도 환경 lock으로 고정한다. 구현 시 capability 검증 후 공개하며 설치/지원 오류는 `unsupported` 또는 `failed`로 반환한다. 기본 환경을 조용히 바꾸지 않는다.

NeuroSim은 PPA만 담당한다. 같은 checkpoint, 선택 풀, nominal Gplus/Gminus, row/column 분할, ADC bits, 측정 VDS=0.1 V와 별도 엔진 읽기 전압 메타데이터, trace hash를 전달한다. Ron=1/Gmax, Roff=1/Gmin을 SI 단위로 전달하고 binary cell의 bit수를 후보 개수에서 자동 계산하지 않는다. 첫 PPA는 1 analog cell/plane/weight, 두 plane 차동 표현의 등가 모델로 평가한다.

기술 노드, read pulse width, ADC 구조, parallel rows, 배선/주변회로 설정은 측정값으로 얻지 못했으므로 실행 preset에 **모두 구체값과 assumed 출처를 저장**해야 한다. upstream 기본값은 참고 시작점일 뿐 CTFM preset으로 자동 채택하지 않는다. V1.4의 기본 SRAM 선택과 노드별 readVoltage/ADC 모델을 확인한 뒤 CTFM 등가 모델의 유효성을 검증해야 한다. 측정 0.1 V를 engine readVoltage에 단순 대입하지 않는다. 검증된 topology/전압 전이 및 모든 effective 설정이 기록된 preset만 실행 가능하게 하며, 그 전에는 PPA를 unsupported로 표시한다. 1 ms write width를 read latency로 복사하지 않는다. preset 파일/hash 없는 PPA 실행은 거부한다.

NeuroSim의 ADC 위치·차동 표현·nonuniform state 지원이 정확도 모델과 같지 않으면 차이를 `model_mismatches`에 기록한다. 구조 대응 자체가 불가능하면 unsupported다. 근사 사용 시 `assumed_equivalent_circuit`으로 표시한다. CTFM 트랜지스터 회로의 실측 PPA로 표현하지 않는다. 시간별 PPA는 v1에서 재계산하지 않으며 nominal/t_ref 기반임을 명시한다.

## 결과

accuracy는 0~1, 화면은 %로 표시한다. `loss_vs_digital_pp=100*(acc_D0-acc_run)`, `loss_vs_mapped_pp=100*(acc_M0-acc_run)`, `retention_loss_pp=100*(acc_t0-acc_t)`로 부호를 보존한다. D2D 반복은 평균·표본 std·p05/p50/p95·전체 배열별 값을 제공하며 seed 분포를 신뢰구간이라고 이름 붙이지 않는다.

PPA는 status, area_m2, energy_j_per_inference, latency_s_per_inference, assumed preset, engine commit, raw output, mismatches를 제공한다. 미실행/실패 값을 0으로 저장하지 않는다. trace 표본은 test 첫 256개로 고정하고 그 표본의 에너지/지연 집계임을 표시한다. 정확도는 전체 test로 평가한다. 시뮬레이션 실행 완료와 물리 모델 검증 완료를 구분한다.
