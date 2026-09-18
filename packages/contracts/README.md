# 프론트·백엔드 공유 계약

실험 요청 schema v1.1.0: [schemas/experiment-request.schema.json](schemas/experiment-request.schema.json).

- fixtures/experiment-*.request.json: 실제 측정값을 포함하지 않는 합성 요청. 예시 UUID는 실제 발행 프로필이 아님.
- check_experiment_contract.py: JSON Schema, 비유한 값, 프로필 revision 중복, 2000회 실행 상한 검증과 self-test.
- openapi/: FastAPI에서 생성할 전체 OpenAPI snapshot은 아직 없음.
- Device Profile/result의 완전한 기계 schema는 서버 구현 시 명세에서 생성해야 함. 현재 요청 계약을 전체 API 구현으로 간주하지 않음.

```sh
python -m pip install -r packages/contracts/requirements-dev.txt
python packages/contracts/check_experiment_contract.py
python packages/contracts/check_experiment_contract.py packages/contracts/fixtures/experiment-effects.request.json
```

실행기는 입력을 읽기만 하며 MNIST 추론이나 실제 프로필 검증을 하지 않는다. 서버는 발행 프로필·측정값·engine capabilities를 추가 검증한다. 권위 있는 동작 명세는 [1차 조건](../../docs/spec/07-first-release-controls.md)과 [API](../../docs/spec/04-web-api.md)다.
