> 상태 변경 (2026-09-18): 이 문서는 과거 계획·검토 또는 기술 참고 자료입니다. 구현 기준은 [확정 설계 v1.0.0](spec/README.md)입니다. 본문의 미확정·승인 대기·이전 규칙은 새 명세를 대체하지 않습니다.

# 소자 원자료 처리와 시뮬레이터 반영 범위 조사

조사일: 2026-09-12
대상: 소자팀 제공 문서 `소자 제공 데이터 정리.pdf`, 현재 저장소의 통합 툴체인·유한상태 설계 문서
상태: **제안(Proposal)이며 미확정·미구현이다.** 아래의 측정 정의와 역할 경계는 소자팀 합의 후 확정해야 한다.

## 1. 결론

소자팀 원자료를 받으면 계산과 시뮬레이션을 한 파이프라인으로 묶는 것은 가능하다. 다만 임의 형식 Excel을 그대로 "자동 이해"하는 방식은 안정적이지 않다. **고정된 열 이름과 단위를 가진 표준 입력 템플릿**을 먼저 합의해야 이후 처리가 단순 파싱과 재현 가능한 계산이 된다.

현재의 사전학습 MNIST 추론 시뮬레이션에 직접 필요한 핵심은 다음 네 가지다.

1. 동일한 읽기 조건에서 얻은 **사용 가능한 유한 전도도 상태 목록**
2. 여러 소자에서 같은 상태를 만들었을 때의 **상태별 D2D 분포**
3. 같은 소자를 여러 번 다시 프로그램했을 때의 **상태별 C2C 분포**
4. 선택 확장인 **상태별 시간 경과 전도도 분포**

Vth, 메모리 윈도우, PPF/PPD, EPSC/IPSC, LTP/LTD 비선형 계수는 계산·표시할 수 있지만, 현재의 정적 MNIST 추론에 모두 직접 쓰이는 것은 아니다. "계산 가능한 지표"와 "AI 추론의 입력 파라미터"를 구분해 보여주는 것이 안전하다.

## 2. 왜 상태별 원자료가 필요한가

AIHWKit의 공식 ReRAM 추론 모델은 목표 전도도 `g_target`에 대해 프로그램 오차를 확률분포로 더하며, 오차 크기가 목표 전도도에 의존할 수 있다. 즉, 소자 범위 전체에 표준편차 하나만 주는 것보다 상태별 평균·분산을 확보하는 편이 실측 특성을 더 잘 보존한다. [AIHWKit ReRAM inference](https://aihwkit.readthedocs.io/en/latest/reram_inference.html) (접속 2026-09-12)

IBM AIHWKit은 D2D와 C2C 파라미터를 지원하고, 펄스 응답의 경계·비선형성·업데이트 크기를 나타내는 여러 소자 모델도 제공한다. 그러나 프로젝트의 실측 유한 상태 목록과 분포를 그대로 쓰려면 기존 프리셋을 선택하는 것만으로는 부족하고, 저장소에서 이미 제안한 사용자 정의 매핑·잡음 계층이 필요하다. [AIHWKit 공식 저장소](https://github.com/IBM/aihwkit) 및 [공식 pulsed-device API](https://aihwkit.readthedocs.io/en/latest/api/aihwkit.simulator.configs.devices.html) (접속 2026-09-12)

실제 배열 연구도 여러 목표 전도도 각각에 대해 D2D 분포를 측정하고, 한 소자의 반복 읽기 또는 반복 프로그램 상태로 C2C를 구분해 보고한다. 따라서 `Gmin/Gmax` 두 점만으로 전 범위 편차를 대표시키는 것은 강한 근사다. [Nature Communications, 2025](https://www.nature.com/articles/s41467-025-65233-w) (접속 2026-09-12)

## 3. 요청 항목별 처리 분류

| 소자팀 항목 | 표준 파일 이후 단순 파싱 | 계산·분석 알고리즘 | 소자팀 판단이 먼저 필요한 부분 | 현재 AI 추론 사용 | 결과 프로필 표시 |
|---|---|---|---|---|---|
| Id-Vg / Id-Vd | 곡선·소자·상태·스윕 방향별 행 그룹화 | 보간, 미분, 대표 읽기점 추출 | 바이어스, 스윕 방향, 유효 곡선/PASS 기준 | 읽기점의 상태별 G만 사용 | 원곡선, 읽기점, 누설 등 표시 가능 |
| Vth | 계산된 값 읽기 또는 Id-Vg에서 추출 | constant-current 또는 최대 gm 외삽 등 | **추출법과 기준 전류**, 사용할 sweep branch | 직접 사용하지 않음 | 상태별 Vth, 평균·표준편차 |
| 메모리 윈도우 | 두 Vth의 상태/방향 짝 연결 | 두 Vth 차이 계산 | 어떤 두 branch/state의 차이인지, 부호/절댓값 정의 | 직접 사용하지 않음 | 값과 G dynamic range와의 상관 비교 |
| D2D | device_id·state_id별 그룹화 | 상태별 소자 평균 차이, 분산성분 또는 empirical sampling | 비교 가능한 소자 집단·위치, 제외 기준 | **직접 사용** | 상태별 분포·표본 수 |
| C2C | 같은 device_id의 cycle_id별 그룹화 | 상태별 within-device 잔차·분산성분 | 한 cycle의 시작/종료, 초기화, 반복 프로토콜 | **직접 사용** | 상태별 분포·사이클별 정확도 분산 |
| Retention | state_id·시간별 시계열 그룹화 | `G(t)/G(0)`, 적합식, 시간별 분포 | 평가 시간, 손실 정의, 온도/조건 비교 범위 | 선택 확장 | 상태별 곡선·지정 시점 손실·순위 |
| EPSC/IPSC | 시간-전류 파형 읽기 | baseline, peak, decay 추출 | peak window, baseline, 자극 종료 기준 | 현재 정적 추론에는 미사용 | 선택적 소자 특성 카드 |
| PPF/PPD | pulse pair·간격별 그룹화 | 2nd/1st peak 비율과 시간상수 적합 | peak 정의와 PPF/PPD 식 | 현재 정적 추론에는 미사용 | 간격-비율 곡선 |
| LTP/LTD 상태 곡선 | pulse index 순으로 안정화 G 읽기 | 상태 평균, 단계 차이, 비선형 적합 | 상태 채택 기준, P/E 경로와 초기화 정의 | **유한 상태 매핑에 직접 사용** | 상태 곡선, Gmin/Gmax, 비선형성 |
| Weight states 수 | 후보 상태 행 읽기 | 분포 겹침·간격 기준으로 구분 가능성 평가 | 허용 오분류율/분리 기준, 최종 채택 상태 | **직접 사용** | 후보 수와 채택 수를 따로 표시 |
| Dynamic range | Gmin/Gmax 읽기 | `Gmax/Gmin` 계산 | endpoint가 아니라 usable-state 범위인지 확인 | 매핑 범위에 사용 | 비율과 절대 범위 표시 |

Vth 추출에는 여러 방법이 있고 constant-current 방식은 기준 전류 선택에 따라 결과가 달라진다. 따라서 프로그램이 임의로 방법을 정하면 안 된다. [Keysight Vth extraction 설명](https://www.keysight.com/blogs/en/tech/sim-des/mosfet-threshold-voltage-extraction) (접속 2026-09-12) 또한 forward/reverse Id-Vg에서는 서로 다른 Vth가 나타날 수 있으므로 메모리 윈도우 계산 시 branch 정의가 반드시 필요하다. [Tektronix Vth hysteresis 설명](https://www.tek.com/vn/documents/application-note/sic-mosfet-threshold-voltage-testing-based-on-jedec-jep183a) (접속 2026-09-12)

PPF의 식도 논문마다 `A2/A1` 또는 `(A2-A1)/A1 × 100%`처럼 표현 방식이 달라질 수 있다. 소자팀 문서의 정의를 데이터 사전에 고정해야 한다. 한 실험 예에서는 후자의 식과 pulse amplitude/width를 함께 명시한다. [Nature Communications, 2022](https://www.nature.com/articles/s41467-022-33393-8) (접속 2026-09-12)

## 4. 권장 표준 입력 구조

한 개의 표준 workbook 안에 아래 sheet를 두는 방식을 제안한다. 측정 장비의 원본 파일은 보존하되, 시뮬레이터 업로드용 표만 이 형식으로 내보낸다.

### 4.1 공통 식별·조건 열

모든 sheet가 가능한 한 다음 키를 공유한다.

- `profile_id`, `device_id`, `device_group` 또는 실제 위치 좌표
- `measurement_type`, `state_id`, `direction`(program/erase 또는 up/down)
- `cycle_id`, `pulse_index`, `read_index`
- `valid`와 제외 사유: 소자팀이 판정한 유효성만 전달하며 시뮬레이터가 물리적 실패를 임의 판정하지 않는다.
- 단위가 포함된 열 이름 또는 별도 `unit` 열

여기서 `device_group`은 단순 메타데이터가 아니라 D2D 집단을 정의하는 입력이다. "비슷한 위치"를 컴공팀이 파일만 보고 추측할 수 없으므로, 소자팀이 좌표 전체를 주거나 비교 그룹을 명시해야 한다.

### 4.2 `IV` sheet

- 필수 열: `device_id`, `state_id`, `cycle_id`, `sweep_direction`, `VGS`, `VDS`, `Id`
- 조건 열: sweep 시작·끝·간격·속도, 고정된 다른 단자 전압, 측정 대기/적분 시간
- 선택 열: `Ig`

Vth·메모리 윈도우 계산을 요청한다면 `Vth_method`와 해당 기준값도 합의해야 한다. Id-Vd로 읽기 전도도를 만들 때는 사용할 `VGS_read`, `VDS_read`를 소자팀이 지정해야 한다.

### 4.3 `PULSE_STATE` sheet - 현재 시뮬레이션의 핵심

- 식별: `device_id`, `cycle_id`, `direction`, `pulse_index`, `state_id`
- 쓰기 펄스: polarity, amplitude, width, interval, pulse count/sequence
- 읽기 조건: `VGS_read`, `VDS_read`, 마지막 쓰기 후 `read_delay`, read pulse width 또는 DC 여부
- 측정값: `Id_read` 또는 `G_read`

`Id_read`만 받는다면 같은 읽기점에서 `G_eff = Id_read / VDS_read`로 유효 전도도를 계산할 수 있다. 이 값은 해당 바이어스에서의 등가값이며, 비선형 Id-Vd 전체를 대표하는 물질 상수로 해석하지 않는다.

**D2D와 C2C를 함께 분리하려면** 동일한 상태 정의로 여러 소자를 측정하고, 각 소자에서 같은 전체 P/E pulse train을 여러 cycle 반복해야 한다. 자료 형태는 `G[device, cycle, state, direction]`이어야 한다. 여러 소자를 한 번씩 측정한 파일과 별도의 대표 소자 하나를 반복 측정한 파일만으로도 근사는 가능하지만, 두 변동 성분과 상태 간 상관을 깔끔하게 분리하기 어렵다.

### 4.4 `RETENTION` sheet - 선택 확장

- `device_id`, `cycle_id`, `state_id`, `time_since_program`
- `VGS_read`, `VDS_read`, `read_delay/read cadence`, `Id_read` 또는 `G_read`
- 온도 등 서로 다른 조건을 섞는다면 조건별 그룹 키

현재의 모든 중간 가중치 상태에 retention을 적용하려면 여러 대표 state의 `G(t)`가 필요하다. Program/Erase endpoint 두 상태만 있으면 두 endpoint의 retention 비교와 제한적 보간만 가능하다. 실제 연구에서도 여러 초기 전도도 상태와 공통 읽기 조건을 기록해 시간별 변화를 모델링한다. [Nature Communications, 2021](https://www.nature.com/articles/s41467-021-25455-0) (접속 2026-09-12)

### 4.5 `STP` sheet - 현재는 프로필용 선택 데이터

- `device_id`, EPSC/IPSC 또는 PPF/PPD protocol 이름
- pulse polarity/amplitude/width/interval과 pulse 시작·종료 시각
- sample time, measured current, read bias

이 자료를 정적 MLP/CNN에 억지로 넣지 않는다. 향후 temporal/reservoir/SNN 과제를 별도로 정의할 때 입력 동역학 모델로 확장할 수 있다.

## 5. 자동 계산 파이프라인과 역할 경계

### 5.1 컴공팀이 표준 입력에서 자동화할 수 있는 일

1. 열·단위 검사와 누락 검증
2. `Id/VDS` 기반 읽기점 유효 전도도 계산
3. 합의된 방식의 Vth 및 메모리 윈도우 계산
4. 상태별 평균, 표준편차, 신뢰구간, error-bar용 데이터 계산
5. 계층형 자료에서 D2D와 C2C 분산성분 분리
6. Gmin/Gmax, dynamic range, pulse-state 곡선, retention loss, PPF/PPD 계산
7. 합의된 모델식에 따른 non-linearity·retention 계수 적합
8. 결과 프로필과 시뮬레이터 입력 artifact 생성

### 5.2 소자팀에 반드시 요청할 판단·정의

1. 동일 종류/D2D 비교 대상으로 볼 소자 집단 또는 위치 좌표
2. 측정 실패·전류 제한·이상 곡선의 `valid/excluded` 판정
3. P/E 초기화와 pulse train의 정확한 시작·종료·단계 정의
4. 시뮬레이션용 읽기 동작점 `VGS_read`, `VDS_read`와 read timing
5. Vth 추출법, 기준 전류 또는 gm 외삽 규칙, 사용할 sweep branch
6. 메모리 윈도우를 구성하는 두 Vth와 부호 규칙
7. 사용 가능한 state의 최종 채택 기준 또는 허용 분포 겹침/오분류율
8. retention 순위를 매길 평가 시간과 손실 지표
9. PPF/PPD 비율 및 peak/baseline 정의

컴공팀은 이 정의를 받은 뒤 계산을 자동화할 수 있다. 반대로 이 기준을 코드가 데이터만 보고 자동 추측하게 하면 재현성과 물리적 의미가 흔들린다.

## 6. D2D/C2C 시뮬레이션 설계

### 6.1 권장 계층

측정값을 상태 `s`, 소자 `d`, 재프로그램 cycle `c`에 대해 다음처럼 분해한다.

`G[d,c,s] = mean_G[s] + D2D[d,s] + C2C[d,c,s]`

- `D2D[d,s]`: 가상 배열을 만들 때 한 번 뽑고 그 배열의 모든 재프로그램에서 유지
- `C2C[d,c,s]`: 같은 가상 소자를 cycle마다 다시 프로그램할 때 새로 뽑음
- 가능하면 측정된 device curve와 cycle residual을 empirical resampling해 상태 간 상관을 보존
- 표본이 부족하면 상태별 Gaussian 근사를 사용하되, 근사임을 결과에 표시

실제 문헌에서도 C2C는 각 conductance update에 새 변동을 더하고 D2D는 소자별 응답 계수의 분산으로 따로 모델링한다. [Scientific Reports, 2019](https://www.nature.com/articles/s41598-018-38181-3) (접속 2026-09-12)

### 6.2 `m` 가상 배열 × `n` 재프로그램 cycle

1. 사전학습 가중치를 측정된 유한 conductance state로 매핑한다.
2. 배열 `1..m`마다 D2D realization을 한 번 생성한다.
3. 각 배열에서 `1..n` cycle마다 같은 목표 가중치를 다시 기록하고 C2C realization을 새로 적용한다.
4. cycle마다 동일한 테스트셋으로 추론 정확도를 계산한다.
5. 배열별·cycle별 정확도, 평균·표준편차·분위수, digital 대비 손실을 출력한다.

**중요:** 독립적 C2C만 반영하면 cycle 번호에 따른 결과는 무작위 산포이며, 평균이 계속 낮아지는 "열화 추이"가 아니다. line plot은 순서를 보여줄 수 있으나, 결론은 cycle 간 변동성이다.

누적 P/E 횟수에 따라 평균 G, 분산, usable-state 수 또는 실패율이 달라지는 **endurance/aging 자료**가 별도로 있을 때만 정확도 열화 곡선을 주장할 수 있다. 실제 endurance 실험은 누적 switching cycle에 따른 상태·실패를 측정하며, 일반적인 C2C 분산과 구분된다. [Nature Communications, 2021](https://www.nature.com/articles/s41467-021-25455-0) (접속 2026-09-12)

## 7. 최종 입출력 분류안

### 7.1 실제 시뮬레이터 입력으로 변환할 값

- `state_mean_G[state, direction]`
- `D2D`의 상태별 분포 또는 empirical device curve 목록
- `C2C`의 상태별 within-device 분포 또는 cycle residual 목록
- `Gmin/Gmax`, usable state 목록
- 선택: 상태별 `G(t)` 또는 retention model coefficient
- 공통: 읽기점과 펄스 프로토콜 버전, sample size, 단위

### 7.2 현재 추론에 실제 적용할 값

- 유한 상태 매핑과 차동쌍 `G+`, `G-`
- 배열마다 고정되는 D2D
- 재프로그램마다 바뀌는 C2C
- 선택 시 시간 경과에 따른 retention

Vth/MW의 변동과 G 변동을 동시에 독립 잡음으로 더하면 같은 물리 변화를 중복 계산할 수 있으므로, 현재는 conductance 경로를 시뮬레이션의 기준으로 둔다.

### 7.3 프로필·결과 화면에만 표시할 값

- Id-Vg/Id-Vd 원곡선과 추출된 Vth
- 메모리 윈도우
- Gmin/Gmax와 dynamic range
- 후보/채택 weight states 수
- LTP/LTD non-linearity coefficient
- retention loss와 A1~A5 순위
- EPSC/IPSC, PPF/PPD 지표
- 각 지표의 sample size와 계산 정의

표시 전용 값도 소자 비교·논문 해석에는 유용하지만, "AI 정확도 계산에 사용됨"으로 표시하지 않는다.

## 8. 소자팀에 추가로 확인할 최소 질문

1. D2D 비교 대상은 어떤 device ID/위치 집단인가?
2. 각 소자에서 동일한 P/E pulse train을 몇 cycle 반복할 수 있는가?
3. 모든 device-cycle에서 같은 `state_id`를 pulse index로 맞출 수 있는가?
4. 프로그램 후 얼마 뒤, 어떤 `VGS_read/VDS_read`에서 `Id` 또는 `G`를 읽을 것인가?
5. Vth는 어떤 추출법·기준 전류·sweep branch로 정의할 것인가?
6. 사용 가능한 conductance state를 소자팀이 지정할 것인가, 아니면 분포 겹침 기준을 함께 정해 프로그램이 제안하게 할 것인가?
7. C2C 분산만 볼 것인가, 누적 cycle 열화까지 볼 것인가? 후자라면 어떤 cycle milestone에서 재측정할 것인가?
8. retention 확장은 어떤 state들과 어떤 시간 범위를 대상으로 할 것인가?

이 답을 받으면 재측정 위험이 크게 줄어든다. 특히 2~4번이 없으면 D2D/C2C를 AI 가중치 상태에 정확히 연결하기 어렵다.

## 9. 제안 결정 요약

- **제안:** 원자료 수용 범위는 넓히되, 업로드 형식은 표준 workbook으로 고정한다.
- **제안:** 소자팀이 physical validity와 비교 집단을 정하고, 컴공팀이 그 기준을 코드화해 계산한다.
- **제안:** 현재 추론은 conductance state + D2D + C2C를 중심으로 한다.
- **제안:** Vth/MW/STP 지표는 계산해 device profile에 표시하되 직접 정확도 모델에는 넣지 않는다.
- **제안:** retention은 state별 시계열이 있을 때 선택 확장한다.
- **제안:** `m × n`은 D2D/C2C 정확도 분포 실험으로 명명한다. 누적 열화는 endurance 자료가 있을 때 별도 실험으로 분리한다.
