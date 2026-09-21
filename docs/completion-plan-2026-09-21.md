# 개발 마무리 계획과 완료 기준

> 후속 상태: P0의 알려진 CSV 형식 파싱·후보 추출·프로필 생성/발행 함수 검증을 `2f88b0b`에서 완료했다. 후속 main 6c590ea에서 팀의 LTP/LTD HTTP/브라우저 및 일부 P1 엔진 검증이 추가됐다. ADC 순서 간 통제 비교와 P2~P4 등은 남아 있다. [개발 담당 인수인계](../handoff/02_measurement-fix-and-next-steps.md)를 먼저 확인한다. 아래는 최초 계획이며 전체 완료 보고가 아니다.

2026-09-21 · 진단 기준 fd27e4e. 이번 변경은 지침과 공유 데이터이며 제품 코드 수정이 아니다. [진단 후속 설명](diagnosis-followup-2026-09-21.md), [08 기준 명세](spec/08-hardware-baseline.md), [문헌 근거](research/hardware-baseline-evidence.md)를 함께 읽는다.

## 범위와 우선순위

사용자가 원하는 전체 목표(측정 분석, 정확도 시뮬레이션, 조건부 NeuroSim 비용)를 유지한다. 아래 중간 완료점을 전체 완료로 부르지 않는다. 새 선택지를 추가하기보다 실제 입력과 엔진 연결을 먼저 완성한다.

### P0 실제 데이터 분석부터 profile 발행까지

자료: [최신 CSV와 manifest](../data/reference/ltp-ltd-2026-09-21/README.md).

해결: parse_table에서 명시적 header/data 구간 선택을 지원하고 알려진 장비 형식은 후보를 제안한다. Remarks를 헤더로 오인하지 않고, primary table 뒤의 보조표와 설명행을 분리한다. 자동 인식이 여러 후보를 만들면 선택을 요구한다. 선택한 데이터 내부의 잘못된 행을 조용히 skip하지 않는다. 원본 row/hash 보존.

검증: CSV10/10 읽기, 명시적인 time/Id/Vg 단위·열 대응, manifest의 첫/끝 sample과 j-2 검사, 데이터별 채택·제외 사유, A조건별 profile 발행. 구판11.5uA 기대값 제거/구판fixture로 이동. 실제 사용자 업로드부터 다운로드까지 확인. 재측정 요청이나 원본 수작업 삭제로 parser 결함을 우회하지 않는다.

### P1 정확도 경로 완료

08의 unsigned8bit, 두 G plane, 두 ADC 순서, validation 보정 고정 기준을 유지한다. nominal/input8bit/mapping/ADC/effects 결과를 구분한다. 동일 표본으로 time/ADC 비교. PyTorch와 AIHWKit 지원 조합을 Linux에서 실제 대조하고 capabilities는 worker 환경의 검증 결과에 맞춘다.

검증: 단위 손계산/계약 검사 + 실제 최신 profile로 MNIST 실행 + 브라우저에서 두 순서 선택·작업 완료·결과 확인. 라이브러리를 바꿔 실행한 것을 AIHWKit 성공이라 보고하지 않는다. 데이터 분석의 오류를 시뮬레이터 오류로 뭉뚱그리지 않는다.

### P2 C2C 수동 가정 모드 (권고 구현안)

기존에는 의도적으로 c2c=false였으며 UI 숫자 입력/적용 로직은 없다. 사용자 의도에 따라 파일 parser와 독립된 수동 입력 모드를 먼저 구현하는 것을 권고한다. 다음 모델은 실측 분포가 아닌 공학적 가정이며 08의 미제공 상태를 대체할 확장 계약으로 명시한다.

- 입력: profile별 relative CV %, 출처 manual_assumption, 재기록 반복 수(1~100 권고), seed. 여러 profile에 같은 수치를 적용하려면 명시적으로 선택하며 실측 profile 값을 덮어쓰지 않는다. 기본 CV는 빈 값, off 상태. 실제 측정값처럼 미리 채우지 않는다.
- 권고 분포: 평균1 lognormal 배율. c=CV/100, s=sqrt(log(1+c²)), f=exp(-s²/2+sZ), Z~N(0,1). Gprogram=Gnominal*f_D2D*f_C2C. Retention은 이후 기존 ratio 적용. 이것은 상대 표준편차 c의 양수 배율이라는 수학적 성질을 이용한 모델이며 CTFM 측정 분포 검증 주장이 아니다.
- 배열 내 D2D는 고정, C2C는 재기록마다 셀/plane별 독립 생성. 전체 test 이미지와 시간/ADC 비교에는 동일 기록 표본을 유지. 추론 이미지마다 다시 뽑지 않는다.
- 자동 Gmin/Gmax clipping은 하지 않는다. 관측 pool 경계를 벗어난 비율과 실효 편차를 보고하며 관측 범위가 물리적 절대 한계라고 가정하지 않는다. 비유한 계산은 오류 처리한다.
- 독립성/동일 CV의 상태 간 전이는 모델 가정으로 표시. 온도·피로·cycle trend·read noise는 추가하지 않는다.
- 실행 수는 기존 예산에 arrays×reprogram×years×candidates를 반영하고 초과 요청은 제출 전 거부한다. 각 축과 seed를 provenance에 기록한다. C2C off는 factor=1,n_reprogram=1. C2C on/CV=0은 수치적으로 동일한 무편차 기준.
- API/schema/UI/core/results를 함께 변경한다. 요청 스키마는 호환되지 않는 의미 변경에 대해 새 버전(예:1.3)을 적용하고 1.2 기록을 보존한다. 결과에서 실측 기반과 수동 가정 실험을 구분한다.
- 검증: CV0 동일성, seed재현성, record간 차이/이미지간 고정, D2D factor 보존, 추정CV sanity, 요청 개수 제한. 측정 parser는 형식이 오면 평균/표본std/CV 계산과 실제 분포 확인을 연결한다.

### P3 NeuroSim 실제 사용자 경로 연결

문헌/가정은 08과 근거 문서를 사용한다. 사용자 물리 결정 대기를 다시 만들지 않는다. preset 등록→assumed_proxy 검증→API request→worker→격리 binary→effective config→coverage 결과를 연결한다. 현재 PPA off-only schema와 validated_for_ctfm gate를 그대로 둔 채 완료라 하지 않는다.

가장 먼저 맞출 것은 표현의 의미: 실제 G+/G−, unsigned8bit code와 고정 범위, bit별 ADC 순서, 물리 셀 수와 trace sample 수. 현재 normalized weight/signed128레벨/첫이미지 한 개 경로를 충실한 PPA 입력이라고 취급하지 않는다. 정확도 기준을 엔진 편의에 맞춰 축소하지 않는다.

### P4 회로 비용과 엔진 오류

블록 비용 확보는 엔진 내부 객체를 계측해서 구조화 JSON으로 내보내는 방식 (기존 문서 선택a)을 우선 권고한다. 코드에 존재하는 비용을 추출하므로 별도 경험식을 새로 만드는 범위를 줄일 수 있다. commit/patch/hash와 단위, 집계 중복 검사를 포함한다.

- array/driver/mux/ADC/accumulator/shift-add/buffer/interconnect를 계층별로 구분. shared와 per-plane 비용을 합성한다.
- 단일 sensing 지연을 추출해 read excitation 가정의 성립 여부를 검사한다. 계측만으로 자동 성립하는 것은 아니다.
- digital subtraction은 검증 가능한 adder/subtractor 모델로 구현·계수. analog subtraction/bipolar front end는 별도 회로 근거와 모델이 필요하다. 계측은 존재하지 않는 회로를 만들어주지 않는다.
- 완전한 비용 모델 전에는 partial block estimates와 missing_components, 총계 null. complete PPA라는 라벨 금지. 이것은 중간 결과이지 전체 목표 축소가 아니다.
- 64/128 crash는 최소 재현→debugger/메모리 검사→원인 패치→회귀. 256 smoke 성공은 유지하되 사용자64 요청을256으로 몰래 바꾸지 않는다. 기존 ‘출력96 미만 전부 실패’ 일반화는 사용하지 않는다.

## 완료 보고 형식

개발 담당은 항목별 implemented / tested-synthetic / tested-measured / tested-engine / tested-browser / blocked를 구분하고 명령·환경·commit·data hash·실제 결과를 남긴다. passed 테스트 개수만으로 제품 완료를 선언하지 않는다.

1차 검수는 P0+P1, C2C 수동 실험 확장은 P2, 전체 조건부 하드웨어 결과 완성은 P3+P4로 구분한다. 누락 항목을 공개한 부분 결과와 모든 모델 연결 완료를 구분하며, 기존 구현·측정 파일을 보존한다.
