# 64×64 정확도 모델과 NeuroSim 비용 모델의 정합 (2026-09-26, 작업 12)

기준: 작업 11의 엔진 수정(패치 0001)은 유지. 모델 폭·bit slicing·배열 크기는 바꾸지 않았고 `validated_for_ctfm=false`, `assumed_proxy` 표시도 그대로다. 증거는 `local_report/evidence/12/`. 엔진 패치는 `engine-patches/neurosim/0002-…patch`(README에 플래그 표).

## 1. 정확도 → 엔진 전달 경로 (이전 vs 이번)

| 항목 | 정확도 경로 | 이전 엔진 입력(작업 10~11) | 이번 엔진 입력 | 검증 |
| --- | --- | --- | --- | --- |
| 전도도 | 매핑된 G+, G− (S, 비균일 측정 상태) | 복원 weight `scale·(G+−G−)`을 [−1,1]로 정규화한 한 파일 → 엔진이 8bit 정수로 재양자화 후 256 균일 레벨(Param 기본 Ron 100 kΩ, Roff 1.7 MΩ)로 재매핑. 프로파일 G는 보고만 됐고 엔진에 전달되지 않음 | **G+, G− 각각 siemens 파일**(`%.17g`, 재양자화 없음). 엔진 패치 플래그 `ctfmConductanceInput`이 값을 그대로 셀 전도도로 사용. Ron = 1/Gmax, Roff = 1/Gmin(풀)을 빌드 상수로 고정(캐시 key에 포함) | 엔진이 파생한 열 전도도 합 = 파일에서 독립 계산한 값, 상대오차 < 1e-9 (합성), ~1e-10 (실제 A1 프로파일) |
| 입력 | unsigned 코드 q∈[0,255], `floor(255x/r+0.5)`, bit k = `floor(q/2^k)%2`, LSB 우선 8 cycle | 실수 활성 첫 샘플을 [−1,1)로 정규화, 2의 보수 부호-우선 plane → 비음수 입력의 최상위 plane 손실(유효 7 bit) | **같은 코드의 unsigned 8 plane**(열 k = bit k). C++ 소비 측은 부호를 해석하지 않고 `input==1`이면 행을 켜므로(코드 확인) writer만 고치면 충분 | 0/1/127/128/255/혼합에서 엔진이 읽은 행 수 = 설정된 bit 수 × 열 subarray 수(정확 일치), plane 열 순서를 뒤집어도 비용 동일 |
| 표본 | 고정 test 앞 256개 | 첫 이미지 1개 | 256개 각각을 엔진에 한 번씩(이미지별 bit trace), 평균·표준편차·최소·최대 보고 | 결과 `trace_sample`, `diagnostics.per_image_stats` |
| 두 plane | 두 plane 동시 read, plane별 ADC 또는 뺄셈 후 ADC | plane 하나만(총계 미산정) | `ctfmDifferential`: 한 subarray-cycle에서 두 plane을 함께 평가, plane별 블록(WL 구동·mux·열 읽기/MLSA)은 plane별, shift-add·이후는 1회, 지연은 느린 plane | `identical_planes_cost_the_same`, 면적 = 2×사용슬롯×64²×48F² |
| 배치 | 64×64 논리 타일 ×2 plane | 엔진 PE(2×2 subarray) 패딩 → 131,072셀/plane, layer2를 빈 subarray에 복제(speed-up 2, 명세 위반), write 전용 level shifter 면적 포함(writeVoltage 2 V > 1.5 V, 명세 위반) | `ctfmNoDuplication`, `ctfmReadOnly`(+ writeVoltage 1 V), `ctfmUsedOnly`. 사용 슬롯 = 명세 타일링 28개/plane, 물리 셀 229,376(두 plane), 가중치 셀 101,632/plane | `placement.matches_spec_tiling = true`, 엔진 ledger의 사용 슬롯 = 명세 계산 |

빈 셀 처리(부분 채움 subarray): 셀 자체는 짓고 면적·누설에 포함하지만, 가중치가 없는 행은 WL을 구동하지 않아 read 전류가 없고, 없는 열은 변환하지 않아 동적 에너지가 없다. 가중치가 전혀 없는 subarray 슬롯은 짓지 않는다(PE 수준 공유 회로는 엔진 floorplan 그대로).
변환기 수: 엔진은 슬롯 폭(64열)/8 = 8개/plane, 명세 산술은 실제 열 수 기준 ceil(C/8)이라 부분 열 subarray에서 다르다(424 vs 448 등). `placement.converters_engine/converters_spec_inventory`로 둘 다 표시한다.

## 2. ADC 순서별 비용 (근거 있는 것만 합산)

- `adc_then_subtract`: plane별 MLSA + 디지털 뺄셈기(엔진 `Adder`, ADC bit+부호폭, 열 그룹당 1개, ADC와 pipeline) + shift-add 1회. 산정된 블록: 셀 배열, 행 구동/mux, 열 읽기·감지, 디지털 뺄셈, shift-add, PE/타일/칩 공유 회로, 버퍼, 연결망, 누설. 미산정: `adc_range_scaling`, `digital_bias_add`.
- `subtract_then_adc`: 두 plane 배열·구동·shift-add·공유 회로는 산정. 아날로그 차감 front end와 **부호 있는 열 감지/변환은 근거가 없어 미산정**(엔진 MLSA는 unsigned이고 열 읽기 전류와 감지가 한 SPICE 피팅 식에 묶여 분리할 수 없으므로 열 읽기 에너지·변환기 면적·감지 지연도 주장하지 않는다). 에너지·지연 합계는 null.
- 근거 확인: 엔진 소스(`MultilevelSenseAmp.cpp`, `SubArray.cpp`, `Adder.cpp`)와 NeuroSim 논문(Chen·Peng·Yu, IEEE TCAD 37(12), 2018, doi 10.1109/TCAD.2018.2789723), DNN+NeuroSim V2.0(Peng 외, IEEE TCAD 2020, doi 10.1109/TCAD.2020.3043731; V1.1의 ADC 양자화 영향 포함). 아날로그 전류-거울 차감 등 여러 실현이 있다는 문헌 검색 결과(예: ACM TODAES 10.1145/3569940 계열)는 있으나 우리 가정 회로(22 nm, current-mode)의 면적·에너지·지연 수치를 주는 1차 자료를 찾지 못해 채택하지 않았다.
- 두 순서의 알려진 블록 집합이 다르므로 결과를 “전체 비용 비교”로 표시하지 않는다(UI에 미산정 블록을 항상 함께 표시).
- `known_total`은 알려진 블록 합이며 완전한 PPA도, 하한도 상한도 아니다. `area_m2/energy_j_per_inference/latency_s_per_inference`는 미산정 블록이 있는 한 null이다.

## 3. 시간 검사 (10 ns 읽기 창)

엔진은 synchronous이며 클럭 = 가장 긴 감지 지연(A1, 64: 1.83 ns), 열 정착(bitline settling)은 클럭에서 제외된 별도 값(1.4 ps). 명세의 10 ns는 가상 read excitation이므로 한 입력 bit cycle은 `max(10 ns, 감지/클럭, 열 정착)`이다. 결과의 `schedule_check`가 창 성립 여부·필요 시간·유효 cycle을 보고하고, `window_adjusted` 지연 = 엔진 cycle 수 × 유효 cycle(엔진 원시 지연은 `diagnostics.latency.engine_clock_s`). 누설 에너지는 유효 시간으로 다시 적분한다. 회로가 창보다 느리면 `infeasible`로 표시하고 더 긴 cycle을 쓴다.

## 4. 셀 footprint 한계 (명세 §3의 실패 규칙이 실제로 발동)

엔진은 접근 트랜지스터 폭을 Ron에서 정한다(폭 ∝ 1/Ron, `SubArray.cpp`: `LINEAR_REGION_RATIO/(Ron·0.25)`). 고정 셀 4F×12F에는 폭 12F까지만 들어가고, 넘으면 “Transistor width … larger than the assigned cell width”로 종료한다. 22 nm 모델에서 허용되는 최대 Gmax는 약 174 µS다. A1 풀(0.55~41 µS)은 통과하지만 A3 풀(157~544 µS, Ron 1.84 kΩ → 37.6F)은 통과하지 못한다. 명세대로 footprint와 G를 바꾸지 않고 `failed`(`cell_footprint_exceeded`)와 구체 사유·임계값을 보고하며, A3의 정확도 결과는 그대로 제공한다. **이것은 선택한 가상 1T1R proxy 구성(고정 4F×12F 셀, 22 nm 접근 트랜지스터 모델)의 제약이지 실제 CTFM 소자의 불량이나 성능 판정이 아니다.**

## 5. 정합성 검사 (엔진 종료 코드 0과 구분)

`fidelity`: 첫 이미지에 대해 열 전도도 합, 읽은 행 수, 가중치 셀 수, 사용 슬롯 수를 파일 기반 독립 계산과 비교(통과/실패 표시). `consistency`: 배열/ADC 면적 = 슬롯 수 × 슬롯 면적, ADC 클래스 에너지 = ledger 합. 회귀: 플래그 0의 패치 0002 엔진은 패치 0001 엔진과 stdout 바이트 동일(10 사례).
요청 vs effective: `effective_config.ppa`에 정확도 측(tile/ADC bit/order/입력)과 비용 측(Param 상수, 플래그, 저항 창, 엔진 커밋)을 나란히 두고 필드별 일치를 기록한다.

## 6. 남은 것
1. `adc_range_scaling`(정확도 ADC 범위 R은 엔진 전체 스케일의 약 11~21 %), `digital_bias_add`, 아날로그 차감·부호 감지 회로는 근거 있는 모델이 없어 미산정.
2. 엔진은 출력층에도 activation 비용을 더한다(정확도 모델은 hidden만 ReLU) — mismatch로 표시.
3. 128/256 배열은 엔진 PE 최소 크기 제약으로 PPA 거부(정확도 시뮬레이션은 별개로 제공).
4. A3 이상 큰 전도도 풀은 footprint 규칙으로 비용 평가 불가. 어떤 풀을 연구에 쓸지 또는 셀 footprint 정의를 바꿀지는 설계 결정이다(이번에는 footprint·풀·G를 바꾸지 않았다).
5. 연구용 D2D 소자 쌍 미선정, 원격 push/merge 미실시(인수인계 pending).
