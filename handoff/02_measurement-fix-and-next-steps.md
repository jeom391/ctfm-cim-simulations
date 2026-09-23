# 개발 담당 인수인계 — 최신 진행도

2026-09-21. 확인 기준 main `6c590ea` (PR #4, 구현 커밋 `7e7f10b`). CSV 수정 `2f88b0b`도 이미 main에 포함되어 있다. 이번 인수인계 보완은 `codex/fix-measurement-csv` 브랜치에 공유한다. 사용자의 요청에 따라 추가 제품 구현은 진행하지 않고 개발 담당에게 넘긴다.

## 확인 범위와 근거

이번 점검은 최신 코드, `scripts/measured_workflow.py`, [팀 실행 검증 기록](../docs/verification-2026-09-21.md)을 읽어 대조한 것이다. 팀의 Windows/WSL 실행이나 브라우저 검증을 이 점검에서 다시 실행한 것은 아니다. 아래 수치는 팀 기록의 결과이며, 스크립트가 실제로 검사하는 범위를 함께 명시한다.

## 현재 진행도

| 항목 | 상태 | 남은 점 |
| --- | --- | --- |
| 최신 CSV 10개 파싱·후보 추출 | 구현 및 실측 회귀 검증, main 반영 | 다른 실제 IV/Retention 파일까지 검증됐다는 뜻은 아님 |
| A1~A5 HTTP 업로드→분석→프로필 발행→ZIP 다운로드 | 팀 기록상 통과, 각 조건 후보 1,020개 | 스크립트는 ZIP 목록을 읽으며 내부 모든 값까지 검증하지 않음 |
| 측정 페이지 브라우저 흐름 | 팀 기록상 A3 통과 | A1~A5 모두 브라우저 검증한 것은 아님 |
| 실측 프로필 MNIST 실행 | 팀 기록상 A1 HTTP, A3 브라우저 실행 | 전체 조건·비이상성 조합 검증과 구분 |
| torch_reference ↔ aihwkit_ideal | 팀 기록상 Linux A1에서 각 ADC 순서별 동일 checkpoint 결과 일치 | 두 ADC 순서 사이에는 checkpoint가 달라 우열 비교 불가 |
| 실측 분석 XLSX 내보내기 지연 | 코드 수정 및 팀 회귀 검증 | 팀 기록상 약 5분→7초, 환경 의존 수치 |
| 시뮬레이터 mapping/ADC 지표 표시 | 두 필드명 호환 처리 추가 | 공식 API/결과 계약 이름 통일 필요 |
| 분석 결과 화면의 대형 원시 JSON | 미수정 | 요약·페이지 나눔·필요 시 상세 로딩으로 개선 |
| C2C 수동 입력과 적용 | 이번 main에서 미반영 | 담당 재배정 필요. 이전 문서의 특정 인물/시간 예정은 현행 완료 근거가 아님 |
| NeuroSim PPA 사용자 경로 | 차단 상태 | 가정 모델 계약, preset, API/worker 연결, 비용 검증 필요 |
| NeuroSim crash | 최소 입력 `[[257,1],[1,1]]` 3/3 재현 기록 | 원인 수정·회귀 검증 미완료 |

팀 기록의 전체 테스트 결과는 264 passed / 5 skipped, 웹 테스트 13/13이다. 엔진 probe 성공이나 오류 재현 스크립트의 rc=0은 PPA 계산 성공을 의미하지 않는다.

## measured_workflow.py가 하는 일과 한계

실행 중인 API+worker를 대상으로 원본 SHA256, 서버 업로드 SHA256, preview 시작 행, 분석 후보 수와 첫/끝 원본 행·전류를 검사한다. 프로필 생성·발행·ZIP 다운로드 후 지정 조건만 MNIST를 실행한다. 실험 완료 개수 및 실제 선택 엔진도 확인한다.

기본값은 분석 A1~A5, MNIST는 A1만, torch_reference, ADC 6 bit / subtract_then_adc다. `--checkpoint-id`를 주지 않으면 새 checkpoint가 사용될 수 있다. 한 번 호출해 두 ADC 순서를 자동 비교하는 스크립트가 아니다. 두 번 실행 시 결과를 직접 비교하는 assertion도 없다. 브라우저를 조작하거나 NeuroSim PPA를 켜는 스크립트도 아니다. 실행하면 서버에 분석·발행 프로필·실험을 생성하므로 검증용 환경에서 사용한다.

API+worker 실행 후 예시:

```sh
uv run --locked python scripts/measured_workflow.py --conditions A1 --adc-order subtract_then_adc
# 출력된 checkpoint_id를 아래에 지정하고 다른 조건은 유지한다.
uv run --locked python scripts/measured_workflow.py --conditions A1 --adc-order adc_then_subtract --checkpoint-id <위-실행의-checkpoint-id>
```

이 스크립트는 호출마다 프로필을 새로 만든다. 엄밀한 비교는 동일 profile revision·checkpoint·test/validation 표본·seed·배열 편차·매핑·ADC bits·배열 크기를 고정하고 ADC 순서만 바꾼 두 요청으로 검증해야 한다. checkpoint만 같다고 모든 비교 조건이 같다고 단정하지 않는다.

## 다음 구현 순서

1. **ADC 순서 비교 검증**: 동일 입력 조건에서 순서만 바꾼 두 실행을 저장한다. 기존 표의 정확도 차이는 checkpoint 차이가 섞여 있으므로 순서 효과로 발표하지 않는다.
2. **측정 UI 정리와 계약 통일**: 기본 요약은 후보/채택/제외 수, Gmin/Gmax, 풀 가용 여부, 경고로 제한한다. state ID 전체는 검색/페이지 나눔 또는 별도 다운로드로 제공한다. 접기만 하고 거대한 JSON을 계속 렌더링하는 방식으로 끝내지 않는다. mapping_errors/mapping_metrics, adc/adc_metrics는 API·core·UI·schema에서 공식 이름을 정하고 기존 기록 호환도 유지한다.
3. **C2C 수동 입력**: [마무리 계획 P2](../docs/completion-plan-2026-09-21.md)의 권고 모델을 API/schema/UI/core/results까지 연결한다. 실측 파일 형식 미확정과 독립적으로 진행할 수 있다. D2D는 배열에 고정, C2C는 재기록마다 고정하고 이미지마다 새로 뽑지 않는다.
4. **NeuroSim P3/P4**: preset이 없다는 사실은 현재 차단 원인이지 소자팀 답변을 기다려야만 한다는 뜻은 아니다. [하드웨어 기준](../docs/spec/08-hardware-baseline.md)과 [근거](../docs/research/hardware-baseline-evidence.md)에 맞춰 조건부 가정 모델을 구현해야 한다. 현재 adapter의 validated_for_ctfm 검사에 임의로 true를 넣지 말고 assumed_proxy의 허용 범위·표시·coverage 계약을 연결한다. 실제 G+/G−·입력 인코딩·ADC 순서 일치, 비용 누락 표시, crash 원인 수정과 회귀 검증을 함께 진행한다. 이번 검증은 이 부분을 해결하지 않았다.

전체 목표와 세부 완료 기준은 [마무리 계획 P0~P4](../docs/completion-plan-2026-09-21.md)를 따른다. P0의 LTP/LTD 실측 경로와 P1의 일부 실행 검증이 전진한 상태이며, 전체 시뮬레이터 완료로 보고하지 않는다. Retention/D2D의 실제 데이터 검증 범위도 따로 기록한다.

## 06 작업 갱신 (2026-09-23, local_report/06_TASK_backend-batch.md)

- **정확도/측정 백엔드(A)**: `scripts/measured_workflow.py`를 격리된 API+worker 인스턴스(포트 8100, 별도 storage root)에 대해 실행해 A1~A5 전 조건의 업로드→분석→프로필→발행→ZIP export가 실제 HTTP로 성공함을 재확인(각 1020 states). A1 조건에서 실제 MNIST 실험도 실행: D0=0.9651, D1=0.965, M0=0.9641, ALL=0.9578(기존 문서 수치와 동일, 새 checkpoint로 재현). `--compare-adc-orders`로 동일 checkpoint·profile에서 ADC 순서만 바꾼 실행도 재확인(모든 비교 불변식 통과, accuracy_delta_pp=-0.42). 전체 pytest는 (환경 문제였던 TMPDIR 픽스 후) 322 passed / 5 skipped, 0 error.
- **실측 IV/Retention 연결은 이번에도 진행하지 못했다** — 원본 파일(`관련 자료/IV Sweep/`, `관련 자료/Retention/`, git 제외 폴더)은 존재하지만, IV 파일은 한 시트에 Vg/Id/Ig 열이 여러 번 반복되는 계측기 레이아웃이라 현재 `parse_table`이 인식하는 Time/MeasResult1/MeasResult2 단일 레이아웃과 다르고, Retention 파일은 program/erase가 서로 다른 time 축을 쓰는 2트랙 구조라 `analyze(kind='retention')`이 기대하는 공유 time_s와 형태가 다르다. C2C와 마찬가지로 "형식 미확정" 상태로 보고 새 파서를 만들지 않았다 — 소자팀 확인 없이 임의로 열/시트를 골라 연결하면 근거 없는 매핑이 된다.
- **필드 계약(A5)**: `mapping_errors`는 실제로 설정되지만 `adc`/`adc_metrics`는 백엔드가 아직 채우지 않는다(프런트는 이미 `mapping_metrics ?? mapping_errors`, `adc_metrics ?? adc`로 양쪽을 허용). 이름 통일은 이번에도 하지 않음 — 위 "다음 구현 순서 2"의 그대로 남은 항목.
- **NeuroSim(B/C)**: 이번 세션의 실제 환경(WSL Ubuntu, g++13.3.0 확인됨)에는 `/opt/ctfm-engines/neurosim` 등 엔진 checkout 자체가 없음을 전체 파일시스템 검색으로 확인했다 — 과거 문서의 "빌드 성공" 기록은 이번 세션에서 재현 가능한 상태가 아니다. crash 원인 수정·PPA 실제 실행은 여전히 차단. `validated_for_ctfm`을 임의로 true로 바꾸지 않는 게이트 자체는 코드상 정상 동작 확인(변경 없음).
- **웹 05(측정 화면 재구성/쌍 검증 UI)는 사용자 지시로 중단된 상태 그대로다** — 이번 06 작업에서 프런트 코드는 전혀 건드리지 않았다. `local_report/05_REPORT_measurement-web-flow.md` 참고.
- 세부 근거: `local_report/06_REPORT_backend-batch.md`, `local_report/evidence/06/`.

## 개발 담당 전달 메시지

> 최신 main과 measured_workflow.py 확인했습니다. CSV 분석→프로필→실측 MNIST 실행 및 엔진별 대조까지 진행된 점 확인했습니다. 남은 작업은 같은 조건의 ADC 순서 비교, 측정 화면 JSON 정리와 결과 필드 계약 통일, C2C 수동 입력, NeuroSim 조건부 PPA 연결·crash 수정입니다. 특히 preset 미제공은 소자팀 대기 항목으로 두기보다 확정된 가정 모델 설계에 맞춰 구현할 부분입니다. handoff/02_measurement-fix-and-next-steps.md에 검증 범위와 다음 작업을 정리했으니 읽고 이어서 진행해주세요.
