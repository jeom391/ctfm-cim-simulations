# 최신 개발 인수인계 (2026-09-27)

먼저 [최종 점검·사용 가능 범위](../docs/release-readiness-2026-09-27.md)를 읽으세요. 과거의 “C2C 비활성”, “IV/Retention 미구현”, “NeuroSim 엔진 없음”은 현재 상태가 아닙니다.

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

이번 로컬 검증은 `tmp/fix-measurement-csv` worktree의 `claude/adc-order-comparison`에서 수행했다. 기준 HEAD는 `34e2f3b`이며 이번 최종 수정은 그 이후 변경이다. 바깥 저장소의 오래된 main과 혼동하지 말 것. 원격 push/merge 여부는 별도로 확인해야 한다.

현재 요청 계약은 C2C off 1.2.0, 수동 C2C 1.3.0, 실측 C2C/PPA 1.4.0을 지원한다. 코드·계약의 실제 지원 범위와 각 문서의 과거 버전을 구분한다.

예전 진행 기록은 [보관 문서](archive-status-before-2026-09-27.md)에 남겼다. 보관 문서에 남은 미구현 설명을 현재 상태로 인용하지 않는다.
