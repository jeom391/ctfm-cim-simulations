# 분석·시뮬레이션 작업 worker

Linux Python worker를 구현할 위치입니다. 현재 실행 코드는 없습니다.

- src/ctfm_worker/jobs/: 분석/실험 작업 실행, 진행률, 취소, 오류 처리
- tests/: queue lifecycle과 subprocess 통합 테스트

API가 SQLite queue에 등록한 작업을 처리합니다. API와 같은 DB/관리 artifact root를 사용하며 DB 접근 구현은 중복하지 않습니다. 공통 storage 서비스는 apps/api의 설치 가능한 Python 패키지에 두고 worker가 의존합니다. 연산은 packages/ctfm-core에 위임합니다. 향후 queue 교체 시 계산 라이브러리가 영향받지 않도록 경계를 유지합니다.

AIHWKit/NeuroSim 가용성은 capabilities로 공개하고 engine failure를 참조 엔진으로 묵시 대체하지 않습니다. 기준: [시뮬레이션](../../docs/spec/03-simulation.md), [API/작업 상태](../../docs/spec/04-web-api.md).
