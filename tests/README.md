# 저장소 수준 테스트

- e2e/: 업로드→분석→프로필 발행→시뮬레이션→다운로드 시나리오
- contract/: 서버 응답과 공유 schema, 프론트 계약 호환성

연산 단위 테스트는 packages/ctfm-core/tests, API 통합은 apps/api/tests, worker는 apps/worker/tests에 배치합니다. 루트의 test_measurements.py 등 로컬 미커밋 초기 테스트는 참조 구현 이관 시 함께 옮깁니다. 기존 파일은 구조 정리 과정에서 삭제하지 않았습니다.
