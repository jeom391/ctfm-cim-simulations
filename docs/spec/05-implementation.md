# 구현 순서와 인수 기준

버전 `1.0.0` · [개발 시작](README.md)

## 저장소 위치

통합 앱별 코드 위치와 초기 참조 구현 이관 계획은 [06-repository-structure.md](06-repository-structure.md)를 따른다. 폴더 골격은 생성되어 있으며 아래 P0부터 실제 실행 코드를 구현한다.

## 현재 상태

이 커밋의 목적은 설계와 개발 인수인계 확정이다. 전체 웹·AIHWKit·NeuroSim 구현이나 실제 MNIST 정확도 완료를 주장하지 않는다. 로컬에는 `ctfm/`, `configs/mnist-observed.json`, 관련 테스트의 초기 참조 구현이 있으나 별도 검증·코드 커밋 대상이다. 이번 문서 배포에서 미완성 로컬 코드를 함께 배포하지 않는다. 새 clone에 해당 파일이 없더라도 아래 명세로 개발을 시작할 수 있다.

기존 참조 구현과 새 명세의 차이: common pool, API/프로필 발행, IV·D2D·Retention 분석, lognormal D2D, 시간 외삽, ADC/타일 wrapper, NeuroSim, 웹은 추가 구현이 필요하다. 과거 합성 테스트 통과는 실제 MNIST/엔진 통합 완료가 아니다. 실제 MNIST 다운로드·학습·평가는 아직 완료 결과가 없다.

## 단계별 인수 기준

### P0 계약과 개발 환경

백엔드는 spec에 맞춘 Pydantic 모델·OpenAPI 및 JSON Schema를 생성하고 프론트와 공유한다. 원본은 별도 전달된 로컬 폴더에서 읽으며 fixture는 합성값만 Git에 둔다. Python 3.11 Linux 환경을 통합 worker 기준으로 시작하고 AIHWKit/NeuroSim 설치가 확인된 정확 버전과 commit을 lock한다. 참조 Python 코드는 다른 지원 환경에서도 실행 가능하게 유지한다. 문서 규칙과 충돌하는 adapter 제약은 임의 우회하지 말고 capability로 공개한다.

### P1 측정 분석

- CCM 선형 보간·branch 분리·다중 교차·없음·plateau 테스트.
- MW를 소자별로 구한 뒤 평균내는지 확인.
- 두 소자 D2D N=2 표본 std와 CV RMS를 손계산 fixture로 확인. 조건 불일치와 같은 소자 중복 입력 거부.
- 펄스 양/음 극성, 6초 경계, j-2, ramp 전환, 마지막 구간 제외, 부호/단위/인코딩 검증.
- Retention t<10 제외, log10(s) 계수·단위, 원시값/offset 데이터 구분 검증.
- 기존 A1 파일을 별도 확보한 개발자는 전환1024→읽기1022, LTD ID=1.15e-5 A→115 µS 회귀 확인. 원본 파일 해시와 추출 총수를 실행 산출물에 남김.

### P2 프로필과 기본 추론

- 같은 A조건의 네 풀, 공통 범위 없음, 중복 G 출처 보존, 발행 불변성과 hash 검증.
- 매핑 부호·0·끝점·tie break·실측 후보 membership·scale 고정, brute-force 작은 풀과 pair search 비교.
- 실제 MNIST D0/M0 실행과 모든 유효 후보 결과 저장. 임의 정확도 기준을 만들어 통과시키지 않고 계산 일관성·재현성을 인수 기준으로 사용.
- 테스트셋이 후보 선택/calibration에 쓰이지 않았음을 데이터 흐름으로 확인.

### P3 소자 비이상성과 시간

- D2D 배율의 seed 재현, 같은 배열·시간에서 고정, 극성 소자 독립, 미제공과 0 구별.
- years=0은 M0 또는 D2D t0와 수치 동일. 시간마다 재매핑/정규화/재추출하지 않음.
- 공통 비율의 차동 weight 변화, 고정 digital bias, 읽기 바이어스 전이 경고, 비양수 외삽 invalid 확인.
- D0/M0 대비 손실의 부호, 실패 제외 분모, N=1 std=null 검증.

### P4 엔진과 PPA

- AIHWKit ideal 모드와 torch_reference의 logits parity: CPU float32 고정 fixture 기준 atol=1e-5, rtol=1e-4, 차이가 크면 조사 후 문서화. 전도도 노이즈 중복 적용 금지.
- 손계산 타일 fixture로 부분합→ADC→디지털 합산 순서, 포화율·grid·rounding 검증. 실제 backend parity 실패 시 지원 완료로 표시하지 않음.
- NeuroSim pin/build smoke test, SI 단위, Ron/Roff·ADC·양극 plane 비용·trace 수·preset export 확인. unsupported 구조를 임의 유사값으로 채우지 않음.
- 두 엔진 결과의 모델 차이와 PPA 시간 기준 표시. 실패/미설치 상태가 프론트까지 전달되는지 검증.

### P5 웹 통합

파일 업로드→분석→draft→발행→실험→다운로드 E2E. 입력 오류, 미지원 엔진, common 없음, 일부 실패, 취소, 서버 재시작 중단을 확인한다. API contract fixture로 프론트가 먼저 개발할 수 있다. 초기 mock 수치는 synthetic 표시와 함께 사용하고 연구 결과 화면에 섞지 않는다.

## 개발 착수 메시지

> GitHub의 docs/spec/README.md부터 읽고 역할별 문서로 이동해주세요. 프론트엔드는 docs/spec/04-web-api.md, 백엔드는 01-measurement-analysis.md와 02-device-profile.md, 알고리즘·엔진은 03-simulation.md가 구현 기준입니다. 작업 순서와 인수 기준은 05-implementation.md에 있습니다. 기존 handoff 및 초기 R3 문서보다 이 명세 v1.0.0을 우선합니다. 우선 P0 API 계약을 맞춘 뒤 프론트 목업과 P1 분석 구현을 진행하면 됩니다.
