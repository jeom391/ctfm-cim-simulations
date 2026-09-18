# 공통 측정·시뮬레이션 연산

서버/worker/CLI가 공유할 Python 라이브러리 위치입니다. HTTP, React, DB에 의존하지 않습니다.

계획 Python import namespace는 ctfm이며 소스 root는 src/ctfm입니다. 측정 파싱·분석, 프로필 검증, 상태 매핑, D2D/Retention, 실험 실행 및 엔진 adapter를 이 패키지에 구현합니다. 엔진이 필요 없는 측정 분석은 torch/AIHWKit를 불필요하게 import하지 않도록 나눕니다.

- src/ctfm/measurement/: IV, pulse, D2D, Retention 분석
- src/ctfm/profiles/: 프로필 검증, 풀 생성
- src/ctfm/simulation/: 매핑, 효과, 평가
- src/ctfm/adapters/: torch, AIHWKit, NeuroSim 경계
- tests/: 계산 단위 및 통합 테스트

루트 ctfm/과 pyproject.toml 등은 일부 개발 환경에만 존재하는 미커밋 참조 구현입니다. 아직 이 경로로 이관하지 않았으며 새 clone에는 없습니다. P0/P2에서 검증 후 git 이력과 import를 확인하며 옮깁니다. 동일 구현을 두 경로에서 계속 유지하지 않습니다.

기준: docs/spec의 측정·프로필·시뮬레이션 명세. 패키지 metadata와 lock은 실제 환경 검증 단계에서 추가합니다.
