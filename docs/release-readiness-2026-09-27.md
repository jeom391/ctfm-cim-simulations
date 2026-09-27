# 최종 구현 점검과 사용 범위 (2026-09-27)

## 판정

측정 분석·프로필 생성·MNIST 정확도 시뮬레이션을 사용하는 v1 범위와, 추가 회로 연구가 필요한 완전한 PPA 범위를 구분한다. 전체 가속기 PPA가 완성됐다고 발표하면 안 된다. 최종 구현 커밋 `7ccae46`에 대해 전체 검사, 실측 파일 읽기, 웹 빌드와 사용자 흐름 확인을 마쳤다. 이 문서는 작업 14의 검증 결과와 후속 대조 결과를 반영한다.

| 기능 | 현재 상태 | 해석/사용 조건 |
| --- | --- | --- |
| LTP/LTD CSV와 상태 풀 | 구현 | 쌍 확인·열/단위·시작 시점 확인 후 분석. 후보 상태 수는 구별 가능한 물리 상태 수와 다름 |
| IV·문턱전압·Memory Window | 구현 | 반복 블록과 상승/하강 구간을 명시 선택. CCM 1 µA·선형 보간 |
| D2D | 구현 | 같은 조건의 서로 다른 두 소자를 사용자가 선택. 개발 검증용 쌍을 연구 대표값으로 자동 확정하지 않음 |
| Retention | 구현 | Program/Erase 독립 시간축, 10초 이후 적합. 연 단위 결과는 측정 범위 밖 외삽이며 중간 상태 적용은 모델 가정 |
| C2C 측정 보조 | 구현 | 원본 cycle별 전류에 합의한 3차 추세 적합·상대 잔차 표준편차. 잔차는 순수 독립 잡음으로 검증된 값이 아님 |
| C2C 추론 반영 | 구현 | Program 편차만 사용. Erase는 진단용. 실측 분석 참조/해시 및 가정 승인, 조건 다르면 추가 확인 |
| MNIST 정확도 | 구현 | 디지털 기준·매핑·ADC·D2D·Retention·C2C. 비교할 때 같은 checkpoint/표본/seed를 사용 |
| 웹 결과·내보내기 | 구현 | 요약·상태 목록 페이지 이동·설정과 출처 보존 |
| NeuroSim 부분 비용 | 제한적 구현 | 가정한 선형 1T1R proxy, 64 배열, 패치 0001/0002. 전체 PPA 아님 |
| 전체 가속기 PPA | 미완료 | ADC 범위 스케일링·bias·STA 아날로그 차감/부호 감지 등 미산정. 임의의 0이나 추정값으로 채우지 않음 |

## 이번 점검에서 수정한 결함

1. 외부 NeuroSim 실행 timeout, 파일/실행 오류, 컴파일 실패는 PPA `failed`로 반환한다. 이미 계산한 정확도 결과를 작업 전체 실패로 잃지 않는다. 일반 프로그래밍 오류나 취소를 무조건 숨기지 않는다.
2. 첫 번째 유효 후보의 PPA가 다른 profile/pool/mapping이나 디지털 기준 결과에도 복사되던 문제를 수정했다. 해당 후보의 ALL 결과에만 연결하고, 화면에서 평가 대상과 기준 시점 제한을 명시한다. 다른 후보는 비용 미평가(null)다.
3. 엔진 종료 코드가 0이어도 fidelity 또는 해당 순서에 필요한 consistency 검사가 실패/누락되면 비용 값을 차단한다. 검사 내용과 원시 진단은 남긴다. STA에 적용되지 않는 ADC 검사는 요구하지 않는다.
4. IV 블록의 원시 전압 값에 사용자가 선택한 V/mV 단위를 적용해 스윕 진폭을 V로 변환한다. 단위 변경 시 화면의 자동 진폭과 서버 검증이 일치한다.
5. 인수인계 첫 화면을 현재 상태 하나로 정리하고, 서로 충돌하던 과거 설명을 기록용 문서로 분리했다.

## 남은 항목과 종료 기준

- 현재 v1 사용을 위해 소자팀에 추가 등가 회로 값을 무조건 요구할 필요는 없다. 측정 분석/정확도는 지금 데이터를 사용한다.
- 연구 발표에 쓰는 D2D 소자 쌍과 C2C 대표값 적용 가정은 연구자가 확인해야 한다. 구현 누락과 구분한다.
- PPA 128/256, A3 큰 전도도 풀의 가상 셀 footprint 제약, 출력층 activation 비용·ADC 개수 차이, 미산정 회로는 확장 범위다. 실제 CTFM 소자의 불량 판정이 아니다.
- 구현 커밋 `7ccae46`은 `origin/claude/adc-order-comparison`에 push됐고 실제 원격 해시도 확인했다. main 병합은 별도 검토 단계다. [브랜치 비교·PR 확인](https://github.com/jeom391/ctfm-cim-simulations/compare/main...claude/adc-order-comparison)에서 현재 상태를 확인한다.

## 실행

[루트 README](../README.md)의 API/worker/web 명령을 따른다. API와 worker는 같은 저장소 경로와 `CTFM_STORAGE_ROOT`를 사용한다. NeuroSim/AIHWKit 경로는 [Linux 실행 안내](../scripts/linux/README.md), 패치는 [engine-patches](../engine-patches/neurosim/)를 참고한다. 최신 구현 worktree 대신 오래된 main에서 실행하면 이 상태가 재현되지 않는다.

이전 실측 MNIST·엔진 실행 근거는 [PPA 모델 정합 문서](ppa-model-alignment-2026-09-26.md)에 있다. 작업 14의 상세 보고·로그는 검증한 머신의 `local_report/14_REPORT_release-closeout.md`, `local_report/evidence/14/`에 보관돼 있다. 해당 로컬 원본 로그와 측정 자료는 이 문서 갱신에 포함하지 않았다.

## 최종 검증 결과 (작업 14)

| 검사 | 결과 | 로컬 근거 파일 (`local_report/evidence/14/`) |
| --- | --- | --- |
| 전체 Python | 432 passed / 5 skipped, exit 0 | pytest-full.log |
| 집중 회귀 | 103 passed, exit 0 | focused-post-fix.log |
| 웹 | 34 passed, TypeScript 오류 0, Vite build 성공 | web-verify.log |
| API 계약 | OpenAPI/schema 모두 current, exit 0 | openapi-check.log, schemas-check.log |
| 실측 파일 | IV 50/50, Retention 5/5, 실패 0 | measured-layouts.log, measured-layouts-inventory.json |
| A3 정확도와 PPA 실패 분리 | 두 ADC 순서의 정확도 실험 succeeded, 비용은 footprint 제약으로 failed | a3-ppa-closeout.log, a3-ppa-closeout.json |

건너뛴 5개 검사는 `CTFM_A1_FILE` 환경변수 미지정에 따른 기존 A1 원본 회귀 검사다. 위 55개 실측 파싱 검사의 실패를 뜻하지 않는다. 작업 13에서 중단됐던 전체 검사·원본 파일 재검사는 작업 14에서 완료됐다.

## 웹 확인 범위

- WSL의 API/worker와 최신 웹 빌드에서 A1 LTP/LTD 파일 업로드 → 조건 확인 → 분석(1020 후보 상태) → 프로필 검토·발행을 확인했다. 업로드는 브라우저의 FileList 주입 방식이며 네이티브 파일 선택창 조작을 검증한 것은 아니다.
- 상태 목록 50행 페이지 이동 시 선택 유지, 발행 버튼의 필수 항목 검사, IV의 V/mV 변경 시 진폭 환산, 실측 C2C Program 값 선택·표시를 확인했다.
- A3 프로필·분석·실험 생성은 검증 스크립트의 API 호출로 진행하고, 브라우저에서 정확도와 비용 실패 사유가 함께 표시되는지 확인했다. 이를 전 과정 수동 브라우저 실행으로 표현하지 않는다.
- 평가 대상 profile/pool/mapping 표시와 D0/D1/M0의 PPA null, 해당 후보 ALL의 PPA failed를 확인했다. 다운로드 링크 호출은 프로필 ZIP과 실험 산출물 모두 HTTP 200이었다.
- 이전 uvicorn 모듈 부재는 기존 검증 환경의 라이브러리 경로를 사용해 해결했다. Windows 전용 API/worker 환경은 이번에 별도 재검증하지 않았다.

## 전달 상태

구현과 최종 검증 결과는 `claude/adc-order-comparison` 브랜치를 기준으로 전달한다. 기존 `gh` CLI의 PR 생성 시도는 미인증으로 실패했으나 git push는 성공했다. PR의 최신 상태는 GitHub에서 확인하며, 코드 검증 완료와 main 병합 완료를 구분한다. 이번 문서 갱신은 계산 코드 변경 없이 검증·화면 확인·업로드 상태를 바로잡는 작업이다.

## 팀 전달용 짧은 요약

측정 데이터를 분석하고 그 결과로 MNIST 정확도를 비교하는 주요 기능의 구현과 최종 검증을 마쳤습니다. 자동 검사 432개와 웹 검사 34개가 통과했고, 실측 파일 55개도 정상적으로 읽었습니다. 실제 화면에서 업로드·분석·프로필 발행과 결과 표시를 확인했으며 코드는 GitHub 작업 브랜치에 올렸습니다. 다만 회로 전체의 면적·전력·속도는 아직 일부만 계산하며, main 반영은 PR 검토·병합 단계로 구분합니다.
