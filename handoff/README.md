# 다음 구현 우선 문서 (2026-09-29)

**개발 담당자는 [전체 수정 요구사항](04_next-implementation-2026-09-29.md)을 먼저 읽으세요.** 64×64 고정, PPA UI/기본 실행 제외, 측정 업로드 간소화, 독립 프로필과 비교 묶음, 임시 실행/이름 저장을 다음 구현 범위로 정했습니다. 아직 이 변경을 구현 완료한 상태는 아닙니다.

- [최신 공유 원자료 및 manifest](../data/team-snapshot/2026-09-29/README.md)
- [C2C 미확인 조건 및 파일별 문제](../docs/c2c-data-review-2026-09-29.md)

아래는 **변경 전 구현 상태**입니다. 새 요구사항과 충돌하는 배열/ADC 순서/PPA 화면 설명은 새 문서를 우선합니다.

---

# 최신 개발 인수인계 (2026-09-27)

먼저 [최종 점검·사용 가능 범위](../docs/release-readiness-2026-09-27.md)를 읽으세요. 과거의 “C2C 비활성”, “IV/Retention 미구현”, “NeuroSim 엔진 없음”은 현재 상태가 아닙니다. 작업 14에서 전체 Python 432개·웹 34개 검사, 실측 IV/Retention 55개 읽기와 웹 사용자 흐름 확인을 완료했습니다(기존 A1 환경변수 미지정 검사 5개는 skipped).

## 현재 범위

- 통합 웹: 측정 파일 업로드 → 분석 → 프로필 검토·발행 → MNIST 정확도 실험 → 결과·내보내기.
- 측정: LTP/LTD, CCM 문턱전압·메모리 윈도우, D2D 비교, Retention, 추세 제거 C2C.
- 시뮬레이터: 상태 풀/매핑, D2D, Retention, Program C2C, ADC 두 순서·3~8 bit·64/128/256 배열.
- NeuroSim: 0001/0002 패치 엔진 + tile 64에서 조건부 **부분 비용**. 완전한 PPA 총계는 제공하지 않음. A3처럼 가상 셀 footprint를 넘는 풀은 비용 평가 실패지만 정확도는 제공.
- PPA는 첫 유효 profile/pool/mapping 후보의 기준 시점만 평가. 다른 후보의 비용으로 재사용하지 않음. 후보별 비용을 보려면 후보별로 실행.

## 읽는 순서

1. [최종 상태·수정·검증·남은 한계](../docs/release-readiness-2026-09-27.md)
2. [설계 명세 목차](../docs/spec/README.md), [하드웨어 기준](../docs/spec/08-hardware-baseline.md)
3. [실측 C2C 및 IV/Retention 연결](../docs/integration-finish-2026-09-26.md)
4. [NeuroSim 모델과 부분 비용의 해석](../docs/ppa-model-alignment-2026-09-26.md)
5. [API 실행](../apps/api/README.md), [Linux 엔진 환경](../scripts/linux/README.md)

## 개발 위치와 전달 상태

최종 구현 검증은 `tmp/fix-measurement-csv` worktree의 `claude/adc-order-comparison`, 구현 커밋 `7ccae46`에서 수행했다. 해당 커밋의 원격 push와 해시 일치를 확인했다. 후속 문서 갱신은 계산 코드 변경을 포함하지 않는다. 바깥 저장소의 오래된 main과 혼동하지 말 것. main 병합은 별도이며 [브랜치 비교·PR 상태](https://github.com/jeom391/ctfm-cim-simulations/compare/main...claude/adc-order-comparison)를 확인한다.

브라우저 업로드는 FileList 주입, A3 실험 생성은 API 스크립트, 결과 표시는 실제 브라우저로 확인했다. 네이티브 파일 선택창이나 모든 실험을 수동 웹 조작으로 검증했다고 표현하지 않는다. 전체 확인 범위와 알려진 PPA 한계는 위 최종 상태 문서에 정리했다.

현재 요청 계약은 C2C off 1.2.0, 수동 C2C 1.3.0, 실측 C2C/PPA 1.4.0을 지원한다. 코드·계약의 실제 지원 범위와 각 문서의 과거 버전을 구분한다.

예전 진행 기록은 [보관 문서](archive-status-before-2026-09-27.md)에 남겼다. 보관 문서에 남은 미구현 설명을 현재 상태로 인용하지 않는다.
