# 측정 분석·비교 화면 갱신과 검증 범위

2026-09-30 기준. [2026-09-29 구현 인수인계](../handoff/04_next-implementation-2026-09-29.md)의 범위 축소와 화면 흐름을 반영했다. 이전 명세의 PPA·배열 선택·ADC 순서 선택은 신규 실행 정책의 근거가 아니다.

## 신규 실행 정책

- 측정 분석과 MNIST 정확도 비교를 제공한다. 신규 실행의 배열은 64×64, 입력 인코딩은 unsigned 8 bit이다. ADC는 OFF 또는 3–8 bit이며 새 비교의 기본값은 ON 5 bit다. ON이면 각 경로를 변환한 뒤 차감하는 `adc_then_subtract`, OFF이면 순서가 `null`이다.
- API와 worker가 같은 제품 정책으로 128/256 배열, 다른 ADC 순서, `preset_id`, PPA 요청을 거부한다. 요청 값을 몰래 바꾸지 않는다. 신규 결과의 PPA 상태는 `not_evaluated`이며 면적·에너지·지연은 `null`이다. 정상 정확도 실행은 NeuroSim 비용 입력 생성·평가·가용성 탐색을 호출하지 않는다.
- 과거 실험과 프로필, 과거 PPA 결과는 당시 설정 그대로 읽는다. 저수준 연구용 코드가 남아 있어도 신규 제품 실행의 허용을 뜻하지 않는다.

## 사용 흐름과 데이터 경계

`측정 분석`에서 여러 CSV/XLSX를 올리고 자동 인식 결과의 출처·해시·원본 행·조건 근거를 확인한다. 명확한 LTP/LTD 쌍과 다른 준비된 분석은 한 번에 제출할 수 있다. IV 블록/세그먼트와 모호한 조건은 사용자가 명시적으로 고른다. 분석 완료만으로 프로필이 발행되거나 C2C 적용이 승인되지 않는다.

`시뮬레이션`에서 서버에 저장되는 비교 초안을 만들고 카드마다 분석과 상태를 독립 선택한다. 각 카드의 새 프로필 revision은 출처·상태 범위·가정을 검토하고 카드별 검토 기록으로 발행한 뒤 연결한다. 공통 ADC·효과·반복·seed·엔진을 한 번 설정한다. 실행은 발행 revision과 설정의 스냅샷, 공통 체크포인트·표본 분할을 사용한다. 임시 결과는 이름을 붙여 저장하거나 새 초안으로 복제할 수 있으며, 명시적으로 버릴 수 있다. `저장한 결과`는 임시 작업과 보관 결과를 구분한다.

## 실제 브라우저·엔진 확인

전용 로컬 실행 환경의 브라우저에서 최신 스냅샷 LTP/LTD 10개 CSV를 순서를 섞어 업로드했다. 인식은 A1–A5의 준비된 쌍 5개를 제안했고 5개 분석이 완료됐다. A1 상태 분석에는 양의 실측 후보 1,020개(각 방향 510개), 원시 행 24,000개, 근거가 표시된 제외 4개가 있었다. A1/A3는 각각 1,020개 후보를 명시 선택하고 독립적인 검토 후 프로필 revision 1로 발행했다. 이는 시험용 관찰 상태 범위의 채택이며 물리적 포화 검증은 아니다.

실제 AIHWKit 1.1.0 비교 실행 `149f2528-6646-4151-b76e-be972312a6a4`는 두 카드 모두 `aihwkit_ideal`의 M0/ADC 5 bit 행을 기록했다. 공통 D0/D1은 `torch_reference`로 계산됐다. 각 행의 MNIST 시험 표본은 10,000개였다.

| 실행 행 | 정확도 |
| --- | ---: |
| 공통 D0 / D1 | 0.9646 / 0.9648 |
| A1 M0 / ADC 5 bit | 0.9643 / 0.9589 |
| A3 M0 / ADC 5 bit | 0.9647 / 0.9448 |

체크포인트 `6d48611d-4cf5-4c79-9cd3-77223e8cb784`(SHA-256 `17dbf1cb2d6fe011cccc36bab47f654ab5865ea5203042c37315f77dff17ce59`)와 분할 SHA-256 `d633100cfb366988a8ab624603277b1df2e7af896d86dbd05ad115f264ba2577`을 공유했다. 훈련/검증/시험은 55,000/5,000/10,000, seed는 20260917이었다. 적용 설정은 64×64, `adc_then_subtract`, unsigned 8 bit였다. A3의 C2C 분석 링크는 저장돼 있지만 C2C/D2D/Retention은 이 실행에서 OFF였고 C2C runtime 적용값은 `null`이다. PPA는 `not_evaluated`이고 비용 값은 모두 `null`이다.

이 결과는 해당 프로필·체크포인트·효과 OFF 조건의 소프트웨어 정확도 확인이다. 물리 가속기의 PPA, 소자 포화, 미확인 C2C 측정 조건의 채택, D2D 물리 소자 동일성 확정의 근거가 아니다.

브라우저에서 첫 결과에 이름을 붙여 저장하고 저장 목록에서 다시 열어 공통 기준·카드 결과·다운로드를 확인했다. 복제 초안에서는 같은 원자료를 다시 올려 얻은 A3 C2C 분석만 새 프로필 revision 2에 연결하고 별도로 검토·발행했다. 기존 A3 revision 1과 저장 결과는 그대로 남았다. 복제 실행 `674ab93d-0c79-4be3-92e8-25e8f85cca81`은 원래 체크포인트·분할을 재사용했고 C2C OFF이므로 여섯 정확도 값이 첫 실행과 같았다. 실행 시작 뒤 수동 새로고침 없이 D0/D1과 17개 다운로드 링크가 나타나 종료 전환 재조회 수정도 실제 브라우저에서 확인됐다. 복제를 버린 뒤 원래 저장 결과는 남고 복제 실험은 제거됐다. 읽기 전용 검사는 기존 보호 대상 엔티티 102개·파일 87개의 바이트 해시가 그대로임을 확인했다. 발행 카드 요약은 저장된 combined pool의 관찰 G 범위 5.53e-7–4.12e-5 S를 표시했다.

## 측정자료 제외와 남은 연구 질문

- 최신 A3 1,000-cycle C2C 파일은 Program 0.047767%, Erase 0.051833%의 추세 제거 통계를 냈다. 측정 조건이 확인되지 않았고 잔차는 iid로 단정할 수 없다. 파일 인식·통계 완료와 시뮬레이터 적용 승인은 별개다. 이번 정확도 실행은 C2C OFF였다.
- A2 C2C의 `--`, `nA`, 음수 원자료와 A4의 결측·cycle 공백은 임의 보간·절댓값 처리하지 않았다. 두 조건의 C2C를 실행 가능한 제안으로 만들지 않았다. A1/A3/A5의 일부 통계적 준비 상태도 시뮬레이터 채택을 뜻하지 않는다.
- D2D의 서로 다른 물리 소자 ID 근거는 미해결이다. A1/A2 파일명이나 조건 ID만으로 서로 다른 소자라고 가정하지 않는다. 원본 측정 스냅샷은 바이트 그대로 보존했다.

## 검사와 증거

WSL의 기존 AIHWKit Python 환경에서 전체 Python 회귀는 478 passed, 12 skipped, 5 warnings, 13 subtests passed였다. 변경된 NeuroSim fixture·계약 테스트 121개도 별도로 통과했다. 웹 테스트 48개와 TypeScript/Vite 빌드 41 모듈, OpenAPI·JSON Schema snapshot 및 실험 계약 검사가 통과했다. 기존 개인 경로의 측정 파일을 요구하는 12개 skip은 통과로 세지 않는다. 브라우저의 실험 상세가 완료 전 응답에 머물러 공통 D0/D1과 다운로드가 늦게 보이던 경로는 실행 중→종료 상태 전환 시 다시 읽도록 수정하고 위 복제 실행에서 확인했다. 상세 명령·경고·로컬 증거 경로는 이 작업공간의 `local_report/18_REPORT_scope-ui-refresh.md`에 기록했다.

## 최종 인식 화면 보완

새 업로드가 현재 배치를 교체하면 이전 파일별 선택과 사유를 지우며, 재인식 요청도 현재 배치의 파일 ID만 직렬화한다. 같은 배치를 다시 인식할 때 입력한 선택은 유지된다. 스냅샷 해시가 없는 Retention 원본에서 `retention_source_required`가 발생하면 Erase/Program 각각의 시간·전류 단위를 네 개의 독립 선택으로 받는다. 원본 라벨, 읽기 VGS, 선택 사유와 함께 서버에 전달하며 단위는 추정하지 않는다.

이 두 경로의 웹 회귀를 추가한 뒤 웹 테스트는 **50 passed**, TypeScript/Vite 빌드는 **41 modules**, exit 0이었다. 별도 합성 파일 네 개의 펄스 CSV와 Retention XLSX를 기존 인식기로 확인했으며 처음에는 `needs_choice`, 명시적 선택 뒤에는 모두 `ready`였다. 이는 소프트웨어용 합성 검증 자료이며 새 실측 증거가 아니다. 위의 전체 Python 478개 및 MNIST 실행 수치는 이전 범위 검증 결과로 유지한다. P3 진단 목록 분량 문제는 이번 수정 범위에서 제외했다.

## PR #7 안정화 수정 (2026-09-30, 리뷰 기준 커밋 f2a61b2 이후)

이 절은 위 범위(측정 분석·비교 화면 갱신)를 앱 기능으로 바꾸지 않고, 그 구현에서 발견된 두 결함을 고친 기록이다. "문서만 변경, 앱 기능 변경 없음"이라는 이전 설명은 이 시점부터 더 이상 맞지 않는다 — 아래는 실제 코드 변경이다.

**1. DB 잠금으로 worker가 종료되던 문제.** `POST /comparisons/{id}/run`이 `BEGIN IMMEDIATE` 이후 엔진 확인·checkpoint 해시·프로필/C2C 검증(느릴 수 있음)을 그대로 수행해, 그동안 worker의 `claim`/`progress`/`finish` 쓰기가 SQLite busy-timeout을 넘기면 처리되지 않은 예외로 worker 프로세스 전체가 죽었다. 재현: `validate_product_scope`를 1초 지연시키고 `/run` 호출 중 별도 job을 `claim()`한 결과 5.6초 대기(수정 전) → 0.5초 미만(수정 후). 수정: 검증을 쓰기 트랜잭션 밖으로 옮기고, 작업 등록 직전 짧은 트랜잭션에서 초안 버전·상태만 재확인(발행 프로필은 불변이므로 그것으로 충분) 후 커밋. `Store`에 SQLite busy/locked 전용 제한 재시도(`_retry_locked`, 최대 3회)를 추가해 `claim/set_pid/progress/finish/cancel/put_entity`에 적용했고, `runner.py`의 `claim()`과 실패-기록(`finish`) 경로를 잠금에 강인하게 만들어 일시적 잠금으로 worker가 죽거나 실행 중 계산이 불필요하게 취소되지 않게 했다.

**2. 새로고침·복제 후 프로필 기준 revision이 끊기던 문제.** `Comparison.tsx`가 "다음 revision을 만들 기준 프로필" 참조를 클라이언트 메모리(`baseRefsRef`)에만 보관해, 새로고침·복제 때마다 비워졌다. 이후 카드의 분석 연결(C2C 등)만 바꾸면 `profile_ref`가 로컬에서 지워지고 기준 참조도 없어, `compose()`가 `POST /profiles`(새 profile ID, revision 1)로 갔다. 수정: `ComparisonCard`에 서버가 초안과 함께 저장하는 `base_profile_ref` 필드를 추가하고(`profile_ref`와 분리 — 실행용 발행 참조와 다음 revision을 만들 편집 기준 참조는 다른 것), 발행 시점에 두 필드를 함께 갱신한다. 클라이언트 전용 `baseRefsRef`/`baseRefs` 상태는 완전히 제거했다. 브라우저로 확인: 합성 프로필 카드를 만들고 새로고침(전체 페이지 리로드) 후 DOM에서 두 select의 값을 직접 읽어 "발행 프로파일 revision 사용"과 "이전 프로파일에서 새 revision 만들기" 모두 같은 `{profile_id}:1`을 유지함을 확인했다(수정 전에는 후자가 비었을 것).

**3. 비이상성(D2D/C2C/Retention) ON 연결 검증.** 기존 UI/스키마를 확장하지 않고, 화면→API→worker→계산→저장까지 실제로 연결됨을 확인했다. 합성 프로필(`SYNTHETIC_TEST_ONLY`, 실측 아님, 조건 분산이 있는 states 10개 + D2D/Retention fit 포함)로 같은 checkpoint·seed·ADC·pools·mappings를 유지한 채 5가지 실행(OFF 기준, D2D만, C2C만, Retention만(0/10년), 셋 다 ON)을 `torch_reference`로 수행했다. **AIHWKit(`aihwkit_ideal`)은 이 환경에 설치돼 있지 않아 사용하지 못했다** — API의 `/capabilities`는 이를 이미 `available:false`로 정확히 보고하며, UI도 실행 결과에 "AIHWKit ideal is unavailable; no AIHWKit parity claim is made"라고 표시한다(제품이 이미 갖추고 있던 정직성 장치를 그대로 확인한 것). 결과: D2D만 ON → array_index 0/1/2가 서로 다른 정확도(0.9491/0.9552/0.9423, 기준 0.9586); C2C만 ON → reprogram_index 0/1이 서로 다른 정확도(0.9558/0.9526)이며 저장된 진단 JSON의 `cv_percent`가 설정한 8.0과 정확히 일치, `seed_key`가 (seed, profile_hash, array_index, reprogram_index, plane, 부호)로만 구성돼 이미지별로 다시 뽑지 않는 기존 규칙이 유지됨을 확인; Retention만 ON → years=0은 기준과 정확히 동일(0.9586, 정의상 비율 1), years=10은 다름(0.9611); 셋 다 ON → 12개 행 모두 정상 계산. 결과 이름 저장 → `/saved-results` 재조회로 지속 확인. **API 스크립트로 5개 시나리오 행렬을 수행했고, 그중 D2D-ON 1개 시나리오는 실제 브라우저(카드 구성→ON 설정→실행→결과 이름 저장→저장한 결과에서 다시 열기)로 별도 확인했다.** API 전용으로 수행한 나머지 4개 시나리오를 브라우저 전체 검증으로 표기하지 않는다. 이 결과는 소프트웨어 연결 확인이며 실제 CTFM 소자나 AIHWKit 물리 모델의 성능 주장이 아니다.

검증: 회귀 테스트 3건 신규 추가(`test_storage.py`: 실제 별도 연결로 쓰기 잠금을 유지했다 해제하는 테스트 포함 2건, `test_worker.py`: claim/finish 잠금 생존 3건, `test_comparisons.py`: `/run` 검증 중 쓰기 잠금 미보유 재현 1건, `workflows.test.ts`: `base_profile_ref` 재로드/복제 생존 1건). 전체 Python 회귀 `packages/ctfm-core/tests apps/api/tests apps/worker/tests tests`: **484 passed, 12 skipped(사설 경로/환경변수 미설정, 기존과 동일), 1 failed**(`test_experiment_summary_accounts_for_the_reprogram_multiplier` — `execute()`를 `runner.run_once()` 없이 직접 호출해 artifacts 디렉터리가 없는, 이번 PR과 무관한 기존 결함. git stash로 수정 전/후 동일하게 실패함을 확인해 이번 변경과 무관함을 확인했고 별도 후속 작업으로 분리했다). 웹 테스트 **51 passed**(신규 1건 포함), TypeScript/Vite 빌드 **41 modules**(전과 동일), `packages/contracts/export_schemas.py --check`·`export_openapi.py --check` 모두 current. 64×64 고정과 신규 실행의 NeuroSim/PPA 미호출은 코드를 건드리지 않았으므로 그대로 유지된다. 자세한 수치·재현 스크립트·경로는 `local_report/21_REPORT_final-stability-effects.md`에 있다.

## PR #7 후속 수정 (2026-09-30, 커밋 f61f7f9 리뷰 반영)

**1. 잠금 재시도 한도 초과 후 작업 상태 복구.** `runner.main`이 잠금 예외를 잡고 계속 실행하지만, 이미 claim한 작업의 `finish()`까지 잠금으로 실패하면 DB에 `running`으로 남고, `recover_interrupted()`는 시작할 때만 호출돼 이후 잠금이 풀려도 복구되지 않는 결함을 수정했다. `store.finish(...)`가 재시도 끝에도 잠금이면 그 결과(state/result/error)를 `<job_dir>/pending-finish.json`에 그대로 적어두고(`_finish_or_defer`/`_FinishDeferred`), 매 `run_once()` 호출 시작 시(그리고 worker 시작 시 `recover_interrupted()`보다 먼저) `_flush_pending_finishes`가 대기 중인 결과를 다시 커밋 시도한다. 실제 반복 실행 모드에서 검증: `test_completed_job_outcome_survives_a_lock_that_outlives_the_retry_budget` — 진짜 subprocess로 분석을 끝까지 실행하고, `finish()`를 첫 호출만 잠금 실패하도록 만든 뒤, 1회차 `run_once()`는 작업을 `running`으로 남기고 `pending-finish.json`을 생성함을 확인, 2회차 `run_once()`(새 작업 없음, 순수 폴링)가 그 파일을 커밋해 `succeeded`로 종료됨을 확인 — subprocess는 정확히 한 번만 실행됐고(재계산 없음), 성공 결과도 손실되지 않았다.

**2. 이전 비교 기록의 base_profile_ref 복구.** 수정 전에 저장된 기록은 `profile_ref`만 있고 `base_profile_ref` 키 자체가 없다. `editableCard()`(새로고침·복제로 카드를 서버에서 받아 편집 상태로 되돌리는 지점)에서 `base_profile_ref`가 없고 `profile_ref`는 있으면 그 값을 그대로 기준 참조로 복구하도록 했다. 브라우저로 실제 확인: `base_profile_ref` 키가 아예 없는 comparison 레코드(구버전 형태 그대로, DB에 직접 기록)를 열어 "이전 프로파일에서 새 revision 만들기" select가 즉시 `profile_id:1`을 보여줌을 확인 → 새로고침 후에도 동일 → C2C 분석을 다른 값으로 교체(발행 참조 `profile_ref`는 null로 지워짐, 기준 참조는 유지됨을 DOM에서 확인) → "프로파일 초안 생성" → 검토자·검토 기록·체크박스 작성 → "revision 발행 후 카드 연결" 클릭 → `GET /profiles/{id}/revisions/3`로 `status=published`, **동일 profile_id**, revision 3, C2C 링크가 정확히 반영됨을 확인했다.

**3. 실패 테스트 점검.** `test_experiment_summary_accounts_for_the_reprogram_multiplier`를 다시 조사한 결과, 실제 원인은 출력 폴더 준비 누락이 **아니라** 이 세션에서 pytest 임시 디렉터리로 쓴 매우 깊고 긴 경로(로컬 백신 소프트웨어가 기본 TEMP를 권한 없는 경로로 리다이렉트해 우회용으로 잡은 경로)가 Windows의 260자 경로 길이 제한을 넘겨 `trace-test-first-256.npz`/`candidate-*.json` 같은 파일 쓰기가 실패한 것이었다. `run_experiment()`는 이미 자신의 출력 디렉터리를 `mkdir(parents=True,exist_ok=True)`로 만든다 — 짧은 임시 경로(`C:\t\...`)로 같은 테스트를 그대로(코드 변경 없이) 실행하면 통과한다. 이는 WSL/Linux 기준 회귀(경로 길이 제한 없음)에서 이 실패가 한 번도 보고되지 않았던 이유와도 일치한다. **코드·테스트를 변경하지 않았고(삭제·skip 없음), requested/completed/skipped 검증은 그대로 유지된다.** 짧은 경로로 재실행한 전체 회귀는 **486 passed, 12 skipped, 0 failed**.

검증: 신규 Python 테스트 1건(`test_worker.py`), 신규 웹 테스트 1건(`workflows.test.ts`, 기존 1건도 새 필드를 반영해 갱신). 전체 Python 회귀(짧은 basetemp) **486 passed, 12 skipped, 0 failed**. 웹 테스트 **52 passed**, TypeScript/Vite 빌드 **41 modules**, exit 0. C2C 실측 적용(부호·단위·결측·피팅)은 건드리지 않았고, 이번 검증에 사용한 C2C 링크는 모두 합성/가짜 항목이며 실험을 실행하지 않았다(발행 화면 흐름만 확인). 자세한 내용은 `local_report/23_REPORT_final-followup.md`.

## PR #7 최종 마무리 (2026-10-01, 커밋 e552a03 이후)

**1. pending-finish 결과가 재시작 중 유실되는 경합 수정.** 성공 결과가 `pending-finish.json`에 대기 중인 상태에서 worker가 재시작해 첫 `_flush_pending_finishes` 호출도 DB 잠금으로 실패하면, 뒤이어 실행되는 `recover_interrupted()`가 같은 작업을 `state='running'`인 고아 작업으로 보고 무조건 `failed`로 덮어써 유효한 성공 결과를 지워버리는 경합이 있었다. `recover_interrupted()`가 각 `running` 작업에 대해 먼저 `<job_dir>/pending-finish.json` 존재 여부를 확인해, 있으면 그 작업을 이번 스윕에서 완전히 건너뛰도록 수정했다(대기 중인 결과의 반영은 다음 `_flush_pending_finishes` 호출에 맡긴다). 또한 `_flush_pending_finishes`가 `store.finish(...)`의 반환값(`applied`)을 확인해, `False`(경쟁하는 다른 종료 처리가 이미 있었던 경우)면 실제 DB 상태를 다시 조회해 요청한 state와 일치하지 않는 한 `pending-finish.json`을 지우지 않고 다음 호출을 위해 남겨두도록 했다 — 결과 반영 여부를 확인하기 전에 대기 파일을 먼저 삭제하지 않는다. 기존 취소 처리(`store.cancel()`)는 변경하지 않았다.
검증: 신규 테스트 2건. `test_pending_finish_survives_a_restart_whose_first_flush_is_also_locked` — 실제 subprocess로 분석을 끝까지 실행하고 `finish()`가 처음 2회 호출까지 잠금 실패하도록 만든 뒤, "재시작"을 시뮬레이션해 `_flush_pending_finishes`(2회차, 여전히 잠금) 이후 `recover_interrupted()`를 호출하면 `recovered==0`이고 작업이 여전히 `running`으로 남음을 확인(수정 전에는 `recovered==1`이고 작업이 `failed`로 덮어써짐) — 마지막 `_flush_pending_finishes`(3회차, 잠금 해제)가 성공 결과를 정상 반영하고 `states` 2개가 그대로 남아 재계산이 없었음(subprocess 실행 횟수 1회)을 확인. `test_flush_pending_finish_never_discards_an_outcome_that_was_not_actually_applied` — 작업이 이미 `cancel()`+`finish(state="cancelled")`로 실제 종료된 뒤에도 낡은 `pending-finish.json`(`state:"succeeded"` 주장)이 남아 있는 경합을 재현해, `_flush_pending_finishes`가 이를 삭제하지 않고 작업 상태도 이미 커밋된 `cancelled`를 덮어쓰지 않음을 확인. 두 테스트 모두 stash로 수정 전 코드에 대해 정확한 실패(`assert 1==0`, `assert False`)를 먼저 확인한 뒤 수정으로 통과함을 재확인했다.

**2. C2C·D2D 구현과 데이터 승인의 분리 재확인 (코드 변경 없음).** `app.py`/`comparisons.py`에서 `c2c_approved_assumption=True`가 설정되는 경로를 모두 추적한 결과, 카드의 `c2c_approved_assumption` 체크박스를 사용자가 명시적으로 켠 경우에만 설정되며 분석 성공만으로 자동 승인되는 경로는 없음을 확인했다. D2D/C2C는 `defaultCommon`에서 여전히 기본 OFF([workflows.ts](../apps/web/src/lib/workflows.ts))다. A3 1,000-cycle C2C 재측정본은 미검토, D2D 물리 소자 ID 확인도 미해결로 남아 있으며(아래 "남은 데이터 확인 사항" 참고), 이번 라운드는 어떤 방식으로도 이를 검증 완료로 표시하지 않았다.

**3. Retention 비이상성 선택·적용을 신규 실행 범위에서 제외.** 서버 정책(`packages/contracts/product_policy.py`의 `validate_product_scope`)이 `effects.retention=true`인 요청을 `outside_product_scope`로 거부하도록 확장했다. 이 정책은 `/api/v1/experiments`, `/api/v1/comparisons/{id}/run`, worker 서브프로세스 내부의 방어적 재검증(`execute.py`) 세 지점 모두에 이미 걸려 있던 동일 함수이므로 별도 수정 없이 세 곳 모두에 적용된다. 프런트엔드에서는 `Comparison.tsx`의 Retention 체크박스·연수 입력 UI를 제거하고 "Retention 비이상성 선택·적용은 이 비교 실행에서 제외됩니다... 측정 Retention 분석과 외삽 조회는 측정 분석/프로필 화면에서 그대로 제공됩니다" 안내문으로 대체했다. `commonSettings()`와 `restoreCommon()`이 항상 `effects.retention:false, years:[0]`을 내보내도록 해, Retention을 켠 채 저장된 예전 초안을 다시 열어도 자동으로 OFF로 정규화된다(UI에서 숨기기만 하고 실행 경로에 남겨두지 않는다는 요구를 서버·클라이언트 양쪽에서 만족). 측정 데이터 분석 화면과 외삽 조회, 관련 계산 코드(`retention_ratio` 등)와 기존 저장 결과는 전혀 건드리지 않았으며, 외삽식 자체도 변경하지 않았다.
검증: 신규 계약 테스트 `test_product_scope_rejects_retention_selection_for_new_executions`(`tests/contract/test_experiment_request.py`), 기존 `test_comparison_run_rejects_out_of_scope_common_settings_without_jobs`에 `retention` 케이스 추가(`apps/api/tests/test_comparisons.py`), 신규 웹 테스트 `retention non-ideality is always off for this new simulation, even for a legacy draft that had it on`(`apps/web/tests/workflows.test.ts`) — 모두 stash로 수정 전 실패를 먼저 확인했다.

**4. 실측 데이터 최종 검증 (실제 브라우저 + 일부 API 호출, 정직하게 구분).** 전용 로컬 검증 환경(포트 8414, 이번 라운드 전용 storage)에서 team-snapshot 2026-09-29의 실제 A1/A3 LTP/LTD CSV로 진행했다.
- **API 호출로 수행(디스클로저)**: 파일 업로드(`POST /api/v1/files`, multipart)와 인식·분석 제출(`POST /api/v1/measurements/recognize`, `POST /api/v1/analyses`)은 curl 직접 호출로 수행했다 — 브라우저의 `FileList`/`DataTransfer` 주입으로 400~700KB CSV 4개를 올리는 것은 비현실적이라 판단했기 때문이며, 이는 브라우저 자체 fetch가 만드는 것과 동일한 multipart 요청이다. 결과: A1 분석 `c88d53d0-df2e-4480-9ab0-f945c48077a9`(1,020 states, succeeded), A3 분석 `761d0475-5292-441e-8f37-b1dc8d481a88`(1,020 states, succeeded) — 이전 라운드에 기록된 수치와 정확히 일치한다.
- **실제 브라우저로 수행**: `/simulator`에서 새 비교 초안 생성 → 카드 2개에 A1/A3 분석을 각각 연결하고 `전체 유효 후보 선택`으로 1,020개 상태를 모두 채택 → 카드별로 "프로파일 초안 생성" → 검토자·검토 기록·"상태, 연결과 가정을 검토했습니다" 체크박스 작성 후 "revision 발행 후 카드 연결"로 A1(`c9a3cdce...`:r1), A3(`ec6a8cbb...`:r1) 발행·연결 → 공통 설정에서 ADC ON(5 bit), **D2D/C2C/Retention 모두 OFF**임을 `GET /comparisons/{id}` 응답(`effects:{adc:true,c2c:false,d2d:false,retention:false}`)으로 재확인 → "저장된 초안 실행" → job `93827e8b-...` succeeded → 결과 화면에 공통 D0 96.51%/D1 96.50%, 카드 1(A1) M0 96.41%/ALL 95.87%, 카드 2(A3) M0 96.50%/ALL 94.18%, Retention 손실 0.000 %p(OFF이므로 당연), PPA 관련 행 없음을 확인 → 이름 `PR7-round3-item4-A1-vs-A3-real-measurement`을 붙여 저장 → `/saved-results` 목록에서 다시 열어 동일한 결과·다운로드 링크가 재현됨을 확인했다.
- **AIHWKit 미확인 disclosure**: 이 로컬 환경에는 실제 AIHWKit이 설치돼 있지 않다. 결과 화면은 제품이 이미 갖춘 장치대로 "AIHWKit ideal is unavailable; no AIHWKit parity claim is made for this run"을 표시했고, 실행에 사용한 엔진은 `torch_reference`였다. 즉 이번 실측 최종 검증은 **동일 checkpoint·표본 분할·공통 조건으로 A1/A3를 비교한 소프트웨어 정확도 확인**이며, 실제 AIHWKit 물리 엔진에서의 A1/A3 비교는 이 환경에서 **수행하지 못한 미확인 항목**이다(2026-09-30 절의 `aihwkit_ideal` 실행은 그 시점 별도 환경에서 이미 수행되었고 이번 라운드가 다시 반복하지는 않았다).
- 64×64 고정과 PPA 신규 실행·화면 제외는 이번에도 코드를 건드리지 않았으므로 그대로 유지되며, 위 결과 화면에도 PPA 행이 없는 것으로 재확인했다.

**회귀 테스트·계약 검사·웹 빌드**: 전체 Python 회귀(`packages/ctfm-core/tests apps/api/tests apps/worker/tests tests`, 짧은 basetemp) **489 passed, 12 skipped, 0 failed**. 이번 라운드가 건드린 3개 파일만 다시 좁혀 돌린 `tests/contract/test_experiment_request.py apps/api/tests/test_comparisons.py apps/worker/tests/test_worker.py`도 **115 passed**. 웹 테스트(`node --test`) **53 passed**(신규 Retention 테스트 포함), `tsc --noEmit && vite build` **41 modules**, exit 0. 자세한 명령과 수치는 `local_report/25_REPORT_final-closeout.md`에 있다.

**남은 데이터 확인 사항 (소프트웨어 수정과 분리)**: A3 1,000-cycle C2C 재측정본의 측정 조건 확인, D2D 서로 다른 물리 소자 ID 확정은 여전히 미해결이며 이번 라운드도 이를 검증 완료로 바꾸지 않았다 — 이 문서와 코드의 "소프트웨어 수정 완료" 범위는 이 두 항목의 "실측 데이터 확인 대기"와 분리해서 읽어야 한다.
