# 통합 API 서버

FastAPI 진입점과 HTTP 라우트를 구현할 위치입니다. 현재 실행 코드/서버는 없습니다.

- src/ctfm_api/routes/: files, analyses, profiles, experiments, jobs, artifacts, capabilities 라우트
- src/ctfm_api/services/: 요청 검증과 application 서비스
- src/ctfm_api/storage/: SQLite repository, 파일 저장소, 작업 queue
- tests/: HTTP 및 저장소 통합 테스트

장기 학습·분석·엔진 실행은 worker로 전달합니다. API 서버에서 요청 처리 중 직접 학습하지 않습니다. 공통 계산은 packages/ctfm-core를 호출하고 프론트와 같은 수식을 별도 작성하지 않습니다.

기준: [API 계약](../../docs/spec/04-web-api.md). app.py, 패키지 설정, 마이그레이션은 P0 구현 대상입니다.
