# CTFM-CIM Simulations

CTFM 소자의 측정 데이터 분석과 실측 전도도 상태 기반 CIM 추론 평가를 위한 연구용 프로젝트입니다.

## 개발 시작

**최신 확정 설계: [docs/spec/README.md](docs/spec/README.md), v1.0.0 (2026-09-18).**

- [측정 분석 계산 규칙](docs/spec/01-measurement-analysis.md)
- [Device Profile 계약](docs/spec/02-device-profile.md)
- [매핑·비이상성·엔진 설계](docs/spec/03-simulation.md)
- [프론트엔드 화면 및 API](docs/spec/04-web-api.md)
- [구현 순서와 인수 기준](docs/spec/05-implementation.md)

홈에서 측정 데이터 분석과 CIM 시뮬레이션을 별도 기능으로 제공합니다. A1~A5를 각각 평가하며, 초기 R3 중심의 세 시뮬레이터 구조는 폐기했습니다. 현재 확정한 것은 설계이며 전체 서비스 구현이나 실제 정확도 평가가 완료된 상태는 아닙니다.

## 협업

정민: 분석·알고리즘·백엔드. 유현: 프론트엔드. 소자팀: 물리적 비교 대상과 결과 검토.
작업 브랜치는 codex/ 또는 팀에서 합의한 기능 브랜치를 사용합니다. 명세 변경은 버전과 이유를 남깁니다. 코드 변경은 별도 검증 후 반영합니다.

원본 측정 자료와 실험 산출물은 Git에 포함하지 않습니다. 데이터는 팀 내부에서 별도로 공유하고 파일 해시로 버전을 추적합니다. 기존 docs의 조사 문서와 handoff는 참고 기록이며 docs/spec보다 우선하지 않습니다.
