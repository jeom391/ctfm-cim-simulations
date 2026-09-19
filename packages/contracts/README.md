# 공유 계약

현재 실험 요청/응답은 v1.1.0, Device Profile은 v1.0.0입니다.

- `schemas/experiment-request.schema.json`: 확정 입력 계약
- `schemas/device-profile.schema.json`: 실제 core ProfileManifest 모델에서 생성
- `schemas/analysis-request.schema.json`, `analysis-result.schema.json`, `experiment-result.schema.json`: API 모델에서 생성
- `openapi/openapi.json`: 전체 FastAPI 라우트의 실제 계약
- `fixtures/`: 합성 요청과 측정 CSV만 포함; 실제 파일·결과 제외
- `models.py`, `check_experiment_contract.py`: API와 공유하는 요청 검증 및2000회 자원 제한

```sh
uv run --locked python packages/contracts/export_schemas.py
uv run --locked python packages/contracts/export_openapi.py
uv run --locked python packages/contracts/export_schemas.py --check
uv run --locked python packages/contracts/export_openapi.py --check
uv run --locked pytest tests/contract -q
```

이후 `apps/web`에서 `npm run generate:api`를 실행합니다. 생성된 TypeScript ProfileManifest와 ExperimentRequest를 실제 UI 요청/응답 코드가 사용합니다.

해시와 canonical CSV 등 값 사이의 의미적 검증은 JSON Schema만으로 충분하지 않아 core 검증도 실행합니다. 요청 schema 통과만으로 학습을 시작하지 않으며, 서버가 발행 revision·측정값·엔진 상태·checkpoint hash를 확인한 뒤 큐에 등록합니다.
