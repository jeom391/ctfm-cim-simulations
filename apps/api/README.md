# 통합 API 서버

FastAPI API, SQLite 메타데이터/작업 큐, 파일 업로드, 측정 분석 요청, Device Profile 검토·발행·revision, 실험 요청과 artifact 다운로드를 제공합니다. 장기 계산은 별도 worker subprocess가 실행합니다.

저장소 루트에서:

```sh
uv sync --locked --python 3.11
uv run --locked uvicorn ctfm_api.app:app --host 127.0.0.1 --port 8000
```

다른 터미널에서 `uv run --locked python -m ctfm_worker`를 실행합니다.
API와 worker의 `CTFM_STORAGE_ROOT`는 같아야 하며, 기본값은 저장소의 `runtime/`입니다.
웹을 `apps/web`에서 `npm ci && npm run build`한 뒤 API를 시작하면 `/`, `/measurements`, `/simulator`를 제공합니다.

- `/docs`, `/openapi.json`: 실제 구현된 요청·응답 계약
- `/api/v1/capabilities`: 설치 및 adapter 검증에 따른 engine/effect 상태
- `/api/v1/files`, `/analyses`, `/profiles`, `/experiments`, `/jobs`: 생성·조회 흐름
- `GET /profiles/{id}/revisions/{rev}/states`: 검토할 상태 목록
- `POST /jobs/{id}/cancel`: 큐 또는 실행 중 작업 취소
- `GET /artifacts/{id}/download`: 경로 대신 UUID와 hash로 확인하는 다운로드

원본 파일은 UUID 경로에 보관합니다. CSV UTF-8/CP949와 XLSX를 지원하며 파일당100MiB·요청당20개, ZIP 확장200MiB·2000개 항목, 파서100만 행·256열·500만 셀 제한을 적용합니다. 사용자에게 물리 소자·조건·분기·열·단위·행 구간을 확인받으며 자동 비교군/이상값 선택을 하지 않습니다.

프로필 ZIP의 실제 states.csv 바이트 해시, canonical 상태와 manifest 해시를 모두 검증합니다. 발행 revision은 불변이며 재검토는 새 draft revision으로 진행합니다. 프로필 응답은 해시를 보존하도록 원래 숫자 표현을 유지합니다.

실험 요청 v1.1.0의 선택값을 보존하며 없는 프로필은404, 미지원 엔진/효과·미제공 측정치는422입니다. 최신07 명세에 따라 seed는 데이터 분할·학습·배열 생성에 반영합니다. 다른 분할의 체크포인트 재사용은 거부합니다.

오류는 `error.{code,message,field,details,request_id}`이며 기본 응답에 내부 경로/stack trace를 넣지 않습니다. 인증·다중 조직·인터넷 공개 서비스는 범위 밖이므로 팀 로컬/접근 제한된 내부 실행을 기준으로 합니다.

```sh
uv run --locked pytest apps/api/tests tests/e2e tests/contract -q
uv run --locked python packages/contracts/export_openapi.py --check
uv run --locked python packages/contracts/export_schemas.py --check
```
