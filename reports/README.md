# CTFM-CIM 사용 안내 자료 (reports/)

측정 데이터 분석과 CIM 시뮬레이션 프로그램의 **최종 사용법과 실제 실행 결과**를 정리한 폴더입니다.
비전공자용 Notion 사용 안내서를 만들 때의 **근거 자료**로 쓰도록 작성했습니다. 모든 절차와 숫자는 이 PC에서 직접 실행해 확인한 것이며, 확인하지 못한 부분은 각 문서에 "미확인"으로 표시했습니다.

## 읽는 순서

| 순서 | 문서 | 내용 | 이럴 때 읽으세요 |
|---|---|---|---|
| 1 | [local-run-guide.md](local-run-guide.md) | 서버 켜기·접속·끄기, 최초 환경 준비, 저장 위치, 문제 해결 | 프로그램을 처음 켜 볼 때 |
| 2 | [measurement-analysis-guide.md](measurement-analysis-guide.md) | I–V · C2C · D2D · Retention (+LTP/LTD) 분석 절차, 실제 결과 표·캡처, 다운로드 | 측정 파일을 분석할 때 |
| 3 | [simulator-guide.md](simulator-guide.md) | 프로필 만들기 → 실행 → 결과 읽기 → 저장·복제·폐기, 실제 실행 예제 | 정확도 시뮬레이션을 돌릴 때 |
| 4 | [verification-status.md](verification-status.md) | 직접 확인한 것 / 자동 테스트만 / 미확인 / 연구 결정이 필요한 것 | 이 자료를 어디까지 믿어도 되는지 볼 때 |

`assets/` 에는 문서에 연결한 실제 화면 캡처와 그래프가 있습니다(인증 정보 없음).

## 기준 정보

| 항목 | 값 |
|---|---|
| 접속 주소 | http://127.0.0.1:8000 (내 컴퓨터에서만 열림) |
| 저장소 | `C:\Users\jmhwa\.codex\worktrees\handoff-data-refresh\ctfm-cim-simulations` (브랜치 `codex/handoff-ui-data-2026-09-29`, PR #7 Draft) |
| 코드 커밋 | `7832a97` 이후(문서 커밋은 `git log -- reports`) |
| 엔진 | AIHWKit 1.1.0 (WSL Ubuntu 24.04, torch 2.12.0+cpu) |
| 사용한 측정 파일 | 저장소 `data/team-snapshot/2026-10-02/`(I–V, D2D, Retention, LTP/LTD, C2C A2), `data/team-snapshot/2026-10-03/`(C2C A1~A5) |
| 작성일 | 2026-10-05 |
| 기준 문서 | `handoff/06_final-implementation-2026-10-02.md`, `docs/acceptance-handoff06-2026-10-03.md` |

## 이 자료를 읽을 때 꼭 기억할 것

1. **C2C·D2D 숫자는 "대표값"이 아니라 계산 결과입니다.** 상승/하강/초기 중 어느 구간이 대표인지는 소자팀 확인 후 정해집니다. 예제에서 쓴 값(A2 상승 중 6.0755 %, 2.9179 %)은 *예시로 고른 값*이며 연구적으로 승인된 값이 아닙니다.
2. **Retention은 분석 화면에서만** 실측과 10년 외삽을 보여 주며, **정확도 시뮬레이터에는 적용하지 않습니다.** 외삽은 모델이지 수명 보증이 아닙니다.
3. 정확도 차이가 **반복 변동(±0.1 %p 정도)보다 작으면** 어느 쪽이 낫다고 말하지 않습니다.
4. 화면의 시각은 UTC(한국 시간보다 9시간 이름)입니다.

## Notion 안내서로 옮길 때 권장 구성 (제안)

1. 5분 시작하기: local-run-guide 2장 + simulator-guide 5장(예제)
2. 측정 분석: measurement-analysis-guide 1~2장, 분석별 장
3. 시뮬레이터: simulator-guide 3~4장
4. 결과 읽는 법과 주의: simulator-guide 5-3, measurement-analysis-guide C2C "읽는 법과 주의"
5. 문제 해결: local-run-guide 6장
6. 수식·검증 근거는 접어 두는 부록: 각 문서의 "근거" 장
