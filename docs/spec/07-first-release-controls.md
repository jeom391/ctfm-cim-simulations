> **추가 결정:** [08](08-hardware-baseline.md)이 ADC 순서, bitserial, 기본 5bit/64타일, ADC-off tile 계약 및 UI 설명을 구체화합니다. 이 파일은 기존 v1.1 API의 기록입니다.

# 1차 사용자 선택 조건 및 실행 계약

설계/실험 요청 버전 1.1.0. Device Profile 1.0.0 유지. 이 문서는 03/04의 고정 추천값으로 해석될 수 있는 부분과 이전 실험 요청 형식보다 우선한다. 사용자 승인: 사용자가 실행 조건을 선택하고 실제 계산에 반영하는 방향으로 1차 구현한다.

## 1차 범위

| 화면 항목 | 선택/입력 | 실제 반영 | 미지원 처리 |
|---|---|---|---|
| 소자 프로필 | 발행 revision, 최대 5개 | 프로필별 독립 실험 | draft/없는 revision 거부 |
| 전도도 풀 | combined/ltp/ltd/common, 복수 선택 | 해당 실측 후보로 매핑 | common 없는 경우 그 후보 skipped |
| 매핑 | fixed_reference/pair_search, 복수 선택 | 실제 Gplus/Gminus 조합 변경 | 후보 2개 미만이면 skipped |
| D2D | on/off, 배열 수 1~100 | 배열별 고정 소자 배율 | CV 미제공 프로필과 활성화 조합 거부 |
| Retention | on/off, 연수 목록 | 기준 10초 대비 비율, 동일 배열로 시간별 추론 | Program fit 미제공이면 거부 |
| ADC | on/off, 3~8 bit 중 하나 | 타일별 부분합의 clip 및 양자화 | 실제 엔진 지원 전 capabilities 비활성화 |
| 배열 크기 | 64/128/256 정사각 중 하나 | ADC 입력 부분합의 row 분할 및 output column block 배치 | ADC off 시 v1에서는 null |
| seed | 0~2^32-1 정수 | 분할·배열 생성 재현성 | 미기재 거부 |
| 모델 | mnist_mlp_v1 | 784→128→10, 공유 checkpoint | 임의 모델 업로드 후속 |

여기서 배열 크기는 물리 제조 치수 확정값이 아니라 논리적 MAC 타일을 분할하는 가정이다. row 부분합마다 ADC 후 digital 합산한다. output column block은 가중치·bias 결과를 보존하며 PPA cell 배치 검증과는 별개다.

UI는 추천값 combined/fixed_reference, D2D 활성 시 30배열, ADC 활성 시 6 bit/128을 채워줄 수 있지만 사용자가 변경할 수 있어야 한다. 숫자가 내부 상수로 요청값을 덮어쓰면 실패다. baseline은 효과 모두 off로 제공한다. 여러 ADC/크기를 비교하려면 UI가 선택 조합별 독립 요청을 만들고 같은 profile/checkpoint/seed를 공유한다. H1/H2는 이 비교를 편하게 만드는 preset이다.

## 프로필에서 가져오는 값

상태 목록, 관측 Gmin/Gmax, 읽기 VGS/VDS, D2D CV, Retention fit은 자동 표시한다. 실행 요청에서 이 값들을 재입력/override하지 않는다. 프로필을 바꾸려면 새 revision을 발행한다. pulse 폭/간격/횟수 변경으로 새로운 풀을 예측하는 옵션도 제공하지 않는다.

## 효과 설정의 결합

- D2D off이면 arrays=1. on이면 같은 배열 realization을 모든 연수/ADC 조건에서 유지한다. 비이상성 분포는 03의 lognormal 규칙을 사용한다.
- Retention off이면 years=[0]. on이면 0을 포함한 중복 없는 연수 목록(최대 10개, 각 0~100)을 사용한다. 이는 UI/실행 범위 제한이며 100년 예측 신뢰성을 의미하지 않는다. 측정 범위를 벗어나는 모든 값에 외삽 표시를 한다.
- ADC on이면 tile_size, adc_bits, range_policy를 반드시 입력한다. range_policy는 1차에서 validation_max_abs만 제공한다. 사용자 지정 ADC 범위와 SAR/MLSA 구조는 후속이다.
- 명목 매핑 M0의 검증셋으로 레이어별 범위를 보정하고 seed·시간·bits 비교 동안 고정한다. ADC/타일별 test 성능을 보고 범위를 다시 조절하지 않는다.
- ADC off이면 hardware.tile_size/adc_bits/range_policy는 null이다. 이 경우 단순 선형 분할은 정확도 비교 조건으로 노출하지 않는다.
- 모델·bias·매핑 scale을 고정하고 효과가 켜진 조합을 실제 추론한다. 정확도 손실들을 더해 최종 정확도로 만들지 않는다.
- 참조 실행은 torch_reference, 설치·parity 검증된 경우에만 aihwkit_ideal adapter를 노출한다. 여기서 ideal은 AIHWKit 내장 잡음을 끈다는 뜻이며 선택한 프로젝트 D2D/Retention/ADC 처리를 생략한다는 뜻이 아니다.

## 1차 비활성 기능

C2C는 측정 절차/입력 데이터 계약 확정 전 c2c=false, n_reprogram=1이다. 기능 예정임을 표시하되 값을 임의 생성해 켜지 않는다. 실제 데이터 확보 후 분석·프로필·반복 기록 계약을 별도 확장한다.

NeuroSim PPA는 검증된 CTFM 등가 preset 부재로 engines.ppa=off, hardware.preset_id=null이다. 정확도 출력은 가능하지만 면적/에너지/지연 결과를 더미값으로 채우지 않는다. SAR/MLSA, ADC 공유 열 수, 기술 노드, 동시 읽기 행 수, bus/buffer/pipeline, 입력 정밀도는 2차 후보이며 현재 form의 실행 가능한 항목으로 노출하지 않는다. NeuroSim 내장 기본값을 CTFM 검증 결과로 간주하지 않는다.

## 요청 검증 및 실행 흐름

공식 요청 shape는 [experiment-request.schema.json](../../packages/contracts/schemas/experiment-request.schema.json), 합성 예시는 [baseline](../../packages/contracts/fixtures/experiment-baseline.request.json)과 [효과 조합](../../packages/contracts/fixtures/experiment-effects.request.json)이다. 예시 UUID는 실제 프로필이 아니며 schema 통과가 enqueue 가능을 뜻하지 않는다.

1. 브라우저 form → 직렬화된 요청. 비활성 필드를 몰래 적용하지 않는다.
2. 서버 schema 검증 → 동일 프로필의 여러 revision 중복 요청 거부 → 요청 실행 수 계산(최대 2000).
3. 발행 상태/파일 hash/선택 풀/측정값/engine capabilities/자원 검증. 지원 안 되는 옵션은 422, 없는 profile은 404. 프로필에 수치가 없는 D2D/Retention을 0으로 대체하지 않는다.
4. checkpoint_id=null이면 한 번 학습한 checkpoint를 전체 비교에 고정한다. UI 여러 요청 비교는 첫 checkpoint를 받은 뒤 같은 ID를 다음 요청들에 전달한다.
5. 요청값을 포함한 resolved config/hash 저장 → 매핑/calibration → 효과별 실제 실행 → 결과와 effective config 저장.
6. 요청과 effective config의 bits/타일/효과/시간/seed 불일치 시 실패 처리. PPA engine에는 미요청 값을 자동 전달하지 않는다.

실행 수는 profiles×pools×mappings×arrays×years의 상한이다. unavailable 후보가 있어도 enqueue 전 예산 계산에서 포함한다. 디지털 기준 및 명목 M0 부가 계산은 별도 overhead다. 2000/100배열/10시간점 제한은 서버 자원 보호값이며 향후 서버 용량에 맞춰 버전을 올려 변경한다. 비교를 여러 요청으로 나눠도 queue 동시성 제한은 서버가 적용한다.

기본 결과는 명목 M0의 검증 정확도로 후보를 추천하고 모든 유효 후보를 보고한다. D2D·시간·ADC 결과로 풀/매핑을 자동 재선택하지 않는다. pool 목록 입력 순서와 무관하게 combined/ltp/ltd/common, fixed_reference/pair_search 순으로 동률 처리한다.

## 결과와 인수 기준

experiment result는 schema_version=1.1.0, 기존 결과 필드에 requested_config와 effective_config를 포함한다. hardware에는 실제 tile_size/adc_bits/range_policy, calibration artifact hash를 기록한다. 기준 범위·선택값·측정 데이터 hash로 실행을 재현할 수 있어야 한다. 배열별/시간별 정확도, D0/M0 대비 signed %p, 매핑 오차, ADC clip 비율을 제공한다. 여러 정확도가 우연히 같아도 실패가 아니며 중간 계산으로 반영 여부를 확인한다.

필수 계산 테스트:

- 손계산 fixture에서 3 bit와 8 bit의 quantized 부분합 값이 달라지는지 확인.
- 입력 차원을 가로지르는 작은 fixture에서 타일 분할→각 ADC→합산 순서 확인. 큰 타일 하나의 ADC 결과와 구분.
- ADC off는 명목 mapped linear 결과와 일치. zero bound는 zero 출력이며 bias는 마지막에 한 번 적용.
- 같은 seed/배열/연수는 재현되고 ADC bits 변경으로 D2D draw가 바뀌지 않음.
- years=0에서 Retention이 없는 동일 배열 결과와 일치, 다른 연수에서는 전도도 비율을 확인. 정확도 감소 자체를 assert하지 않음.
- 외삽 invalid, common 없음, CV 미제공, unavailable engine 처리를 API부터 결과까지 검증.

현재 저장소에 추가한 것은 확정 입력 계약·합성 fixture·계약 검증기다. 웹 form과 실제 효과 실행기는 개발 담당이 위 인수 기준으로 연결해야 한다. 계약 검증 통과를 전체 추론 구현 완료로 보고하지 않는다.
