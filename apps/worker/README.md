# 분석·시뮬레이션 worker

SQLite 큐를 소비하는 단일 worker입니다. 계산마다 별도 subprocess와 새 artifact 디렉터리를 사용합니다.

```sh
uv run --locked python -m ctfm_worker
# 작업을 최대 한 개 처리하고 종료
uv run --locked python -m ctfm_worker --once
```

API와 동일한 `CTFM_STORAGE_ROOT`를 사용합니다. 기본값은 저장소 `runtime/`입니다.
프로세스 잠금으로 같은 저장소의 중복 worker 실행을 막습니다. 재시작 시 남은 running 작업은 failed/interrupted로 기록하고 자동 재실행하지 않습니다.

취소 요청은 worker가 소유한 계산 subprocess와 그 자식만 종료합니다. 계산 subprocess는 소유 worker의 종료도 감시하여 별도 실행이 남지 않도록 합니다. 성공/실패/취소의 최종 상태는 부모 worker만 기록하며 취소 이후 성공으로 덮어쓰지 않습니다.

분석은 CSV/XLSX 파싱→명시적 행 범위→ctfm.measurement 계산으로 진행합니다. 실험은 발행 프로필·checkpoint hash를 다시 확인하고 ctfm.simulation에 위임합니다. 최초 실제 MNIST 실행은 공개 데이터 다운로드가 필요합니다. 다운로드 실패는 오류이며 합성 데이터로 대체하지 않습니다.

결과에는 JSON, CSV, XLSX, PNG, Markdown, 로그와 실험별 mapping/array/calibration/checkpoint artifact가 포함됩니다. CSV/XLSX 사용자 문자열은 수식 실행을 막습니다. 기존 실행 디렉터리를 덮어쓰지 않습니다.

```sh
uv run --locked pytest apps/worker/tests -q
uv run --locked python scripts/smoke_workflow.py
```

smoke 스크립트는 실행 중인 API/worker를 대상으로 명확히 합성으로 표시한 프로필을 발행하고 실제 MNIST 학습·추론을 실행합니다. 소자 실측 성능 검증이 아닙니다.
