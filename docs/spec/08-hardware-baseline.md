# 하드웨어 비교 기준과 구현 변경 명세

설계 문서 v1.2.0 · 2026-09-20 · 사용자 승인된 개발 기준. **구현·실측 검증 완료를 의미하지 않는다.** 기존 실행 schema 1.1.0과 Device Profile 1.0.0은 이 문서 추가만으로 변경되지 않는다. 새 실행 계약은 아래 조건을 구현하면서 1.2.0으로 추가한다.

이 문서는 03/04/05/07의 ADC 계산 순서, PPA 범위와 충돌하는 부분에 우선한다. 측정 분석·상태 선택·D2D·Retention 규칙은 별도 변경하지 않는다. 개발 시작 전 [PDF 답변과 작업 순서](../implementation-decisions-2026-09-20.md), [근거와 보고서 작성 기준](../research/hardware-baseline-evidence.md)을 함께 읽는다.

## 1. 목적과 모델 구분

- 측정 기반 정확도: 발행된 전도도 상태·D2D·Retention, 추후 C2C를 사용한다. 모델의 소자 종류를 바꿔 임의 오차를 추가하지 않는다.
- 조건부 회로 비용: 측정 전도도를 사용하는 가상 아날로그 회로의 면적·에너지·지연을 추정한다. 실제 제작 CTFM 가속기의 성능으로 표시하지 않는다.
- 사용자 선택: 기존 프로필/풀/매핑/비이상성/seed, ADC bits 3~8, 배열 64/128/256, 두 ADC 차감 순서. ADC off도 유지한다.
- 내부 고정: 셀 근사, 입력 인코딩·정밀도, 주변회로 가정, 엔진 버전. 고정값도 결과 상세와 내보내기에 공개한다.
- 재측정 데이터는 구현 착수 조건이 아니다. 합성 입력으로 구현하고 새 데이터 도착 후 별도 검증한다. 기존 측정치가 재측정으로 대체될 수 있음을 provenance에 남기고 발행 profile을 덮어쓰지 않는다.

## 2. 고정 기준

| 항목 | 기준 | 분류 |
|---|---|---|
| 모델 | 기존 mnist_mlp_v1, 학습된 784→128→10 추론 | 기존 설계 |
| 셀/가중치 | 측정 G+와 G− 두 셀, 가중치 bit slicing 없음 | 설계 |
| 입력·ReLU 출력 | unsigned 8 bit, bit serial, LSB부터 8회 처리 | 설계 가정 |
| 추천 UI 초기값 | ADC 5 bit, 64×64, 차감 후 ADC | 기준 비교점; 최적값 아님 |
| ADC 회로 비용 기반 | current-mode MLSA, 경로별 8열 공유 | 문헌/엔진 참고 |
| 주변 CMOS | 22nm, LSTP, 300K | 가상 주변회로; 실측 소자 공정 아님 |
| 연결/버퍼 | XY bus, register-file buffers, global 128×128, tile 32×32; 나머지는 고정 엔진 config에 보존 | 엔진 기반 가정 |
| 스케줄 | 레이어 순차, pipeline off, 처리량 향상용 가중치 복제 off | 설계 |
| 엔진 | NeuroSim 2DInferenceV1.4, 기준 ac828e6723bf077c9b1423c5c72ff6e4981e90f4 | 현재 팀 구현 기준 |
| 실행 재현 | 엔진 patch/config/compiler hash별 격리 빌드·캐시 | 소프트웨어 설계 |

코드에 없는 동작은 플래그가 존재한다고 구현된 것으로 처리하지 않는다. V1.5는 현재 버전을 대체하지 않으며 최소 재현 오류 해결 시 별도 비교·변경 기록을 남긴다. 빌드 캐시 key는 upstream commit, patch hash, resolved hardware config, compiler/version/flags, target platform을 포함한다. 임시 빌드 완료 후 원자적으로 캐시에 등록하고 동일 key 동시 빌드를 잠근다. 요청값과 effective 설정이 다르면 실패시킨다.

## 3. 셀 근사와 비용의 한계

`measured_conductance_1t1r_proxy_v1`: NeuroSim RRAM + CMOS access 읽기 계산 경로를 사용한다. CTFM을 RRAM이라고 물리적으로 동일시하지 않는다. FeFET를 선택한다고 CTFM이 검증되는 것도 아니다. 쓰기/분극/전하 포획 과정은 이 비용 모델의 대상이 아니다.

- 정확도에는 실제 비균일 G 목록을 유지한다. Ron=1/Gmax, Roff=1/Gmin은 선택 풀에서 자동 계산한다.
- baseline cell footprint는 엔진 4F×12F, access gate 1.1V. 실제 셀 치수/실측 read VGS가 아니다. 접근 소자 폭이 footprint를 초과하면 그 구성은 비용 평가 실패로 보고한다. 자동 확장·G 수정 금지.
- 비용 기준 readVoltage=0.55V, readPulseWidth=10ns. 측정 VDS=0.1V와 명확히 분리한다. **측정점 G가 비용 전압에서 유지되는 선형 저항 근사이며 전압 전이 검증은 없다.** 실제 CTFM 속도/전력으로 표현하지 않는다.
- 측정 읽기 구간 1ms를 최소 sensing latency로 복사하지 않는다. 반대로 1ms라는 숫자 자체를 일괄 금지하지 않는다. 값의 출처와 의미를 검사한다.
- 10ns는 가상 read excitation 조건이다. 회로 settling/ADC 계산 시간이 더 길면 숨기지 않고 유효 스케줄에 반영하며 설정 미성립을 보고한다.
- 추론용 read datapath만 비용 범위로 한다. 쓰기 동작 에너지/시간과 program/erase 전용 회로 면적은 제외하고 제외 항목을 표시한다. upstream의 writeVoltage 기본값으로 level shifter 면적이 몰래 포함되지 않도록 adapter를 수정한다.
- upstream calibration은 `validated=false`를 기준으로 하여 별도 실리콘 보정 계수를 적용하지 않는다. 이 flag와 우리 CTFM 검증 여부는 별개다.
- 실행 모델 유효성은 `assumed_proxy`로 표시한다. `validated_for_ctfm=true`를 단순 승인 표시로 설정하지 않는다. 기존 gate를 변경하되 전도도 전달/회로 구성/누락 항목 검사를 통과한 조건부 추정만 공개한다.

## 4. 정확도 계산의 구체적 순서

양자화 입력은 `q=clip(floor(255*x/r+0.5),0,255)`, 복원은 `x_hat=q*r/255`. 입력 픽셀은 원래 [0,1] 범위 r=1, hidden ReLU는 디지털 checkpoint의 validation 5k 출력 최댓값으로 r을 정한다. r=0인 레이어는 q=0. test 데이터 사용 금지. 음수 입력 모델은 현재 지원하지 않는다.

보정 순서: 입력/hidden 범위 고정 → 실제 G 쌍 매핑 → 양자화 입력으로 nominal validation 추론 → ADC 범위 결정. D2D/Retention 적용 이전이며 이후 재보정하지 않는다. ADC 범위는 profile/pool/mapping/tile/order별로 결정하되 bit 수·배열 표본·경과 시간 간 고정한다. 레이어별 모든 타일/bit-plane 표본을 함께 사용한다.

각 layer, input tile, 입력 bit k에서 `p+ = sum(G+ * bit_k)`, `p− = sum(G− * bit_k)`를 계산한다. 물리 전류는 별도 VDS를 곱하며 단위 변환을 결과에 기록한다.

- `subtract_then_adc`: p+−p−를 먼저 계산하고 레이어 범위 [-R,R]에서 ADC 양자화. R은 nominal validation에서 차이의 abs max.
- `adc_then_subtract`: p+, p−를 각각 [0,R]에서 ADC 양자화 후 차감. R은 두 경로를 함께 본 nominal validation max. 두 경로는 동일 range/bit 수 사용.
- `Q(z)=L+clip(floor((z-L)/(U-L)*(2^b-1)+0.5),0,2^b-1)*(U-L)/(2^b-1)`. 범위가 모두 0이면 출력 0. 양극성 격자는 0을 정확히 표현하지 않을 수 있다.
- 각 bit 결과에 2^k를 곱해 합산하고 r/255 및 기존 weight mapping scale을 적용한다. 모든 input tile을 합한 뒤 digital bias를 1회 더하고 hidden에 ReLU 적용한다.
- 양자화는 bit-plane마다 수행한다. 완성된 MAC 한 번만 양자화하는 기존 v1.1 결과와 동일하다고 취급하지 않는다.
- nominal ADC 보정의 hidden trace는 입력 양자화·매핑은 반영하되 ADC off인 경로로 수집하여 순환 보정을 피한다.
- 0을 포함하는 고정 길이 8 bit schedule 사용, bit 전체가 0인 cycle도 v1에서는 skip하지 않는다. ADC off는 입력 8bit 양자화는 유지하고 ADC만 우회한다.
- FP32 digital baseline, input-8bit digital baseline, mapped ADC-off, ADC-on을 구분해서 입력/매핑/ADC 손실을 분리한다. 디지털 FP baseline에 비이상성을 넣지 않는다.

## 5. 두 차동 회로의 비용

논리 R×C tile은 R×C 배열 두 개를 뜻한다. 각 weight의 실제 G 두 개를 유지하고 engine cellBit로 물리 column 수가 추가 증가하지 않게 한다. 기존 균일 bit-slice wrapper를 그대로 사용하지 않는다. adapter가 물리 셀/배열/변환 수를 직접 검증해야 한다.

- 개별 ADC 후 차감: 두 plane이 동시에 읽으며 각 plane에 ceil(C/8) ADC. 한 경로의 ADC를 다른 plane과 시간 공유하지 않는다. digital subtract 이후 bit significance shift/add. 두 plane의 면적·에너지는 합하고 병렬 read latency는 max 후 공통 누산/차감 시간을 반영한다.
- 차감 후 ADC: 두 plane의 대응 column 신호를 analog subtract한 뒤 ceil(C/8) ADC. signed sensing을 unsigned MLSA 블록 한 개로 단순 동일시하지 않는다. bipolar 변환/차감 front end의 별도 모델이 필요하다.
- 공유 입력 버퍼·최종 누산·연결망은 한 번만 계산하며 plane별 local driver는 각각 계산한다. 칩 전체 결과 ×2 금지.
- 아날로그 차감/front end 비용이 없는 상태에서 해당 모드의 완전한 PPA를 출력하지 않는다. 정확도는 제공하고 알려진 블록 비용은 `partial`, 전체 값은 null 및 missing_components로 보고한다. digital subtraction도 비용 모델 연결 전에는 누락으로 기록한다.
- 실제 mapped G 배열과 동일한 입력 bit trace를 engine read 계산에 전달한다. G를 단순 정규화 weight 파일로 바꿔 균일 상태로 복원하는 기존 입력은 충실한 adapter로 인정하지 않는다.
- ADC numerical range/physical current range의 대응을 기록한다. 이상적인 range scaling front end를 가정하면 그 비용 누락을 표시한다. 임의 범위 보정을 무료 물리 회로로 취급하지 않는다.
- 비용 평가는 nominal t_ref에서 수행하고 시간/D2D별 PPA를 계산한 것처럼 반복 표시하지 않는다. 후속 지원 전 정확도만 조건별 평가한다.
- 실제 trace에서 activity를 산출한다. 첫 이미지 1개 결과를 256개 평균이라 표기하지 않는다. 고정 test 앞 256개 평균 및 표본 수를 보고하고 pipeline interval을 end-to-end latency라 쓰지 않는다.

## 6. 계약과 UI

새 요청 schema 1.2.0에 `adc_order` enum을 추가한다. `subtract_then_adc` 기본, `adc_then_subtract` 비교. 고정 설정은 서버 resolved config에 명시하며 사용자 입력으로 받지 않는다. ADC off에서 order는 적용 안 됨으로 표시한다. v1.1 기록은 원래 계산 의미를 보존하고 자동 재해석하지 않는다. old 요청 지원 또는 명시적 migration 오류 중 하나를 문서화한다.

기존 tile=null(ADC off) 계약은 1.2에서 tile 명시로 변경한다. 물리 배열 크기는 ADC off에서도 의미가 있다. 이상 누산 정확도에서는 tile 크기만 바꿔 불필요한 오차를 추가하지 않는다. ADC off인 비용은 실물 ADC 제거와 동일하지 않으므로 PPA 비교 지원하지 않는다.

| 화면 항목 | 항상 보이는 한 줄 설명 |
|---|---|
| 상태 풀 | 측정된 전도도 중 가중치 매핑에 사용할 상태 범위를 선택합니다. |
| D2D | 소자마다 다른 특성을 반영하며, 같은 배열에서는 그 편차를 유지합니다. |
| 배열 생성 수 | 서로 다른 소자 편차를 가진 배열을 생성해 정확도 분포를 확인합니다. |
| C2C | 같은 상태를 다시 기록할 때 발생하는 전도도 편차를 반영합니다. |
| Retention | 경과 시간에 따른 전도도와 정확도 변화를 모델로 추정합니다. |
| ADC bits | 연산 결과의 변환 정밀도이며 낮을수록 양자화 오차가 커질 수 있습니다. |
| 배열 크기 | 타일 크기를 정하며 연산 분할과 부분합 양자화에 영향을 줍니다. |
| 차감 후 ADC | 두 경로의 아날로그 신호를 먼저 뺀 뒤 숫자로 변환합니다. |
| 개별 ADC 후 차감 | 두 경로를 각각 숫자로 변환한 뒤 차이를 계산합니다. |
| seed | 같은 무작위 소자 편차를 재현하기 위한 번호입니다. |

각 항목에 accuracy/PPA/data-required/unsupported 표시를 실제 capabilities와 일치시킨다. C2C는 자료·계약 연결 전 disabled. 툴팁만으로 설명을 숨기지 않는다. PPA 결과에는 `측정 전도도를 적용한 선형 등가 회로의 조건부 비용 추정` 라벨, model assumptions, excluded/missing components, effective config를 노출한다.

## 7. 인수 조건

1. j=1024 전환 시 source_row=1022를 확인한다. 1024개 전환/1022개 상태 개수 검사로 해석하지 않는다. 수치는 기존 파일 예시이며 새 파일에는 새 provenance 기대값을 사용한다.
2. 손계산 가능한 G pair/bit 입력에서 두 ADC 순서 및 각 bit ADC 결과를 확인한다. ADC off에서 bitserial과 8bit 복원 direct MAC의 일치를 검증한다.
3. nominal 보정 이후 D2D/time/ADC bits 비교에서 범위가 바뀌지 않는지 확인한다. 같은 G pair·난수 표본을 재사용한다.
4. 작은 배열에서 물리 셀 수 2×R×C, ADC 수와 변환 스케줄, 공유 회로 중복 없음, 입력 정밀도와 bit trace를 검사한다.
5. cache 동시 실행 격리, 설정 hash와 effective config 일치, 엔진 실패/미지원/부분 결과 구분을 확인한다.
6. NeuroSim crash 최소 재현부터 수정한다. 출력 10을 96으로 임의 padding하거나 모델 변경으로 숨기지 않는다. 필요한 수정은 patch와 회귀 사례로 남긴다.
7. 재측정 파일로 전체 분석→profile→추론 통합 검증은 별도 완료 표시한다. 이번 문서는 해당 실행 성공을 주장하지 않는다.
