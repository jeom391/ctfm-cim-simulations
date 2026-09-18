# 최신 개발 인수인계

전체 계산·API 설계는 v1.0.0이며 통합 웹 저장소 구조를 v1.0.1로 갱신했습니다. 기존 세 시뮬레이터를 각각 구현하지 않고 단일 웹 앱과 공통 실험 실행기를 사용합니다.

## 먼저 읽을 문서

1. [개발 시작](../docs/spec/README.md)
2. [통합 저장소 구조·이관표](../docs/spec/06-repository-structure.md)
3. [화면·API 계약](../docs/spec/04-web-api.md)
4. [구현 순서와 검증 기준](../docs/spec/05-implementation.md)

## 담당별 시작 위치

- 프론트엔드: apps/web. 홈, /measurements, /simulator 페이지.
- API: apps/api. 업로드·분석·프로필 발행·실험·작업 API.
- 계산/엔진: packages/ctfm-core. 측정/프로필/매핑/비이상성/adapter.
- 장기 작업: apps/worker. queue 처리·진행률·취소.
- 공동 계약: packages/contracts. P0에서 OpenAPI/JSON Schema/합성 fixture 생성.

## 완료와 남은 작업

저장소 골격, 파트별 README, 구조 명세, 이전 문서 archive 이동을 완료했습니다. 현재 폴더는 구현 시작용이며 실행 가능한 웹/API를 만들었다는 뜻은 아닙니다. 기존 루트 ctfm/ 및 초기 설정/테스트는 로컬 미커밋 참조 구현으로 보존했고 이번 배포에는 포함하지 않았습니다. 검증 후 core 패키지로 이관합니다.

개발은 P0 계약/환경 → P1 분석 → P2 프로필·기준 추론 → P3 비이상성 → P4 엔진 → P5 웹 통합 순서입니다. 프론트는 P0 합성 계약으로 먼저 작업할 수 있습니다. 원본 측정 파일·runtime DB·실험 결과는 Git에 올리지 않습니다.

01_current-design-handoff.md는 과거 기록입니다. 본문의 이전 경로나 구현 중지 지시보다 현재 docs/spec를 우선하세요.
