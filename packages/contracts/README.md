# 프론트·백엔드 공유 계약

- openapi/: FastAPI/Pydantic에서 생성한 OpenAPI snapshot
- schemas/: Device Profile, experiment config/result의 JSON Schema
- fixtures/: 단위와 가정 표시가 포함된 합성 요청/응답

현재는 계약 산출물의 자리만 마련했습니다. 실제 schema/fixture는 P0에서 docs/spec를 구현한 뒤 추가합니다. 미완성 예시 schema를 공식 계약으로 게시하지 않습니다. TypeScript 타입은 이 계약에서 생성하며 프론트가 별도 정의한 구조와 수작업으로 이중 관리하지 않습니다.

권위 있는 API 명세: [04-web-api.md](../../docs/spec/04-web-api.md). 실제 생성물 변경은 schema version과 연계해 검토합니다.
