# 팀 PDF 답변 및 개발 재개 지침

2026-09-20 · 검토 대상: origin/main 57af5ec의 `정해야할것.pdf`, `구현못한이유.pdf`. 최신 설계는 [08-hardware-baseline](spec/08-hardware-baseline.md). 이 문서는 구현 완료 보고가 아니라 사용자 합의를 구체화한 작업 지침이다.

## 먼저 읽고 진행할 순서

1. 이 문서: 두 PDF에 대한 답변과 작업 범위.
2. [08 기준 명세](spec/08-hardware-baseline.md): 연산 순서·내부 설정·UI·인수 조건.
3. [근거와 보고서 기준](research/hardware-baseline-evidence.md): 실측/문헌/설계 가정의 구분.
4. 기존 spec 01~07 및 implementation-status를 대조하고 코드 영향 목록을 정리한 뒤 구현한다.

## 정해야할것.pdf 항목별 답변

| 항목 | 결정/담당 |
|---|---|
| A1 셀 모델 | 개발 측: RRAM CMOS-access 읽기 계산을 기반으로 측정 전도도 등가 회로 구현. 실제 CTFM/FeFET 물리 검증 주장 금지 |
| A2 셀 치수 | 비용 baseline 4F×12F 가정. 접근 소자 폭 등 성립 검사 실패 시 수치 미제공; 실측 치수로 표기 금지 |
| A3 접근 구조 | CMOS access, 1.1V baseline. CTFM 측정 VGS와 구분 |
| A4 공정 | 주변회로 22nm LSTP 300K 고정. 소자팀에게 공정 선택을 요청하지 않음 |
| A5 차동 비용 | 실제 두 plane, bit slicing 없음. 각 블록별 비용과 공유 범위를 계산; 전체 2배 금지. 누락 front end는 partial |
| A6 전압 | 측정 0.1V 유지, 비용 0.55V 선형 G 전이 가정 명시. 검증된 실제 소자 비용과 구분 |
| A7 쓰기/읽기 | read datapath 비용만. 10ns 가정 및 실제 계산 지연 검사. 쓰기 비용 제외; 1ms 숫자 일괄 거부 수정 |
| B1 ADC 종류 | current MLSA 내부 고정; signed 차감 front end는 별도 모델 필요 |
| B2 공유 열 | 경로별 8열 고정 |
| B3 bus | XY bus 내부 고정 |
| B4 partial parallel | 사용자 옵션 제외. bit별 한 tile 활성 행 병렬 합산을 우리 adapter로 구현·검증; 공식 wrapper MLC 지원으로 오인 금지 |
| B5 입력 정밀도 | unsigned 8bit, bitserial. 기존 signed trace 변환 수정; MNIST/ReLU 한정 |
| B6 보정 | upstream validated=false baseline; CTFM 검증 여부와 별개. 실제 calibrated 결과라고 표기 금지 |
| C1 설정 전달 | 설정별 격리 빌드·캐시 채택. 물리값 답변 대기 없이 개발 |
| C2 엔진 crash | 최소 재현/원인 분석/회귀 검사. 현재 V1.4 유지, 버전 변경 필요 시 근거 기록. MNIST 모델 임의 변경 금지 |
| C3 AIHWKit | 팀이 확인한 Linux Python3.11/torch2.12/AIHWKit1.1.0 호환 환경 고정 및 재확인. worker capability 기준 노출. 메인 workspace lock을 무심코 변경하지 않음 |
| D1 원본 데이터 | 재측정 예정. 알려진 형식으로 구현 계속, 원본 도착 후 통합 검증. 원본 Git 업로드 불필요 |
| D2 C2C | 동일 소자 reset→같은 기록 조건→read 반복의 개별 전류/조건 필요. 평균·표본 std·CV 계산 구현 가능; 파일 parser와 profile 적용 계약은 형식 도착 후. 활성화 전까지 false 유지 |

## 구현못한이유.pdf 항목별 답변

- A 차동 비용: 두 plane 비용 규칙은 새 명세로 정했다. 아날로그 차감 모델 부재는 구현·모델링 작업으로 남고 사용자 물리 판단 대기가 아니다.
- B PPA: 가정한 등가 회로 평가로 범위를 정의했다. preset checkbox만으로 실제 CTFM 검증을 선언하지 않는다. 엔진 crash는 별도 수정한다.
- C ADC 설정: 격리 build/cache 승인. form→resolved config→binary→effective config 연결을 검사한다.
- D 실측 회귀: 개발 중단 사유 아님. j-2 행 번호 검증 코드를 먼저 수정하고, 대체 측정 파일이 오면 별도 실행한다.
- PDF의 ‘더 진행할 코드 작업 없음’, ‘HEAD 8926fd0, push 없음’은 현재 상태 설명으로 사용하지 않는다. 이미 57af5ec에 팀 구현이 반영됐다. 테스트 통과 수는 담당자 보고이며 이 문서 작업에서 재실행하지 않았다.

## 개발 순서

1. 행 번호 테스트/1ms 무조건 거부 수정. 측정 UI 설명과 synthetic 입력 검증은 병행 가능.
2. 계약 1.2.0, 입력8bit/bitserial, 두 ADC 순서, baseline 분리, 보정 고정 구현.
3. NeuroSim 최소 crash 진단과 격리 cache. API/worker의 엔진 환경 일치 검사.
4. 실제 G/bit trace 전달, 물리 cell count, 블록 비용 합산, PPA coverage 표시.
5. 프론트 capabilities/한줄 설명/결과 라벨 연결. 같은 bit 수가 같은 비용임을 암시하지 않기.
6. 신규 실측 파일과 C2C 형식 도착 후 provenance 포함 end-to-end 검증.

아날로그 subtraction과 감지 range 변환 등 미구현 블록이 있는 PPA를 ‘완료’로 표시하지 않는다. 부분 비용 공개는 허용하지만 누락 블록과 총계 null을 명시한다. 정확도 구현과 PPA 전체 지원 완료는 따로 추적한다.
