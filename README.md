# CTFM-CIM Simulations

CTFM 소자의 측정 데이터 분석과 실측 전도도 상태 기반 CIM 추론 평가를 위한 연구용 프로젝트입니다.

## 개발 시작

**최신 확정 설계: [docs/spec/README.md](docs/spec/README.md), 문서·실험 요청 v1.1.0 / Device Profile v1.0.0 (2026-09-18).**

- [측정 분석 계산 규칙](docs/spec/01-measurement-analysis.md)
- [Device Profile 계약](docs/spec/02-device-profile.md)
- [매핑·비이상성·엔진 설계](docs/spec/03-simulation.md)
- [프론트엔드 화면 및 API](docs/spec/04-web-api.md)
- [구현 순서와 인수 기준](docs/spec/05-implementation.md)

홈에서 측정 데이터 분석과 CIM 시뮬레이션을 별도 기능으로 제공합니다. A1~A5를 각각 평가하며, 초기 R3 중심의 세 시뮬레이터 구조는 폐기했습니다. 현재 확정한 것은 설계이며 전체 서비스 구현이나 실제 정확도 평가가 완료된 상태는 아닙니다.

- [1차 사용자 선택 조건·요청 스키마](docs/spec/07-first-release-controls.md)

## 통합 웹 구조

```text
apps/web          하나의 웹 앱: 홈 / 측정 분석 / CIM 시뮬레이터
apps/api          통합 FastAPI 서버
apps/worker       장기 분석·시뮬레이션 작업
packages/ctfm-core  공통 계산 및 엔진 adapter
packages/contracts 공유 OpenAPI / JSON Schema
configs           실험·하드웨어 설정
runtime           로컬 업로드·DB·결과 (Git 제외)
docs/archive      이전 3개 시뮬레이터 문서
```

[저장소 구조·이관 안내](docs/spec/06-repository-structure.md)와 [최신 인수인계](handoff/README.md)를 참고하세요. 현재 앱 폴더는 구현 시작용 골격이며 실행 코드·설치 설정은 P0부터 추가합니다.

## 협업

정민: 분석·알고리즘·백엔드. 유현: 프론트엔드. 소자팀: 물리적 비교 대상과 결과 검토.
작업 브랜치는 codex/ 또는 팀에서 합의한 기능 브랜치를 사용합니다. 명세 변경은 버전과 이유를 남깁니다. 코드 변경은 별도 검증 후 반영합니다.

원본 측정 자료와 실험 산출물은 Git에 포함하지 않습니다. 데이터는 팀 내부에서 별도로 공유하고 파일 해시로 버전을 추적합니다. 기존 docs의 조사 문서와 handoff는 참고 기록이며 docs/spec보다 우선하지 않습니다.
