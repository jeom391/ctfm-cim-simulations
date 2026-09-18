# 통합 웹 저장소 구조

구조 명세 v1.0.1 · 2026-09-18 · 계산/API schema v1.0.0 유지

## 단일 서비스와 페이지

React 웹 앱 하나에 홈(/), 측정 분석(/measurements), CIM 시뮬레이터(/simulator)를 둔다. 기존 세 시뮬레이터는 별도 앱으로 개발하지 않는다. 모델 비교·ADC 민감도·소자 비이상성 비교는 하나의 실험 실행기와 같은 결과 계약을 사용하는 설정/탭이다. 기존 측정 계산 규칙은 변경하지 않는다.

```text
apps/
  web/                 React + TypeScript, 페이지/공통 UI/API client
  api/                 FastAPI, 업로드/프로필/실험/작업 HTTP API
  worker/              장기 분석·학습·추론·PPA 작업
packages/
  ctfm-core/           HTTP/DB 독립 Python 계산과 엔진 adapter
  contracts/           OpenAPI, JSON Schema, 합성 contract fixture
configs/
  experiments/         버전 관리 실험 preset
  hardware/            가정과 엔진 버전을 명시한 회로 preset
data/                  별도 공유 원본과 재생성 데이터, Git 제외
runtime/               업로드·DB·artifact, README 외 Git 제외
tests/
  contract/            공유 schema/API 호환성
  e2e/                 서비스 전체 흐름
handoff/               현재 인수인계 및 과거 기록
docs/
  spec/                현재 구현 기준
  archive/             과거 simulations 및 shared 구조 기록
```

## 의존 방향과 코드 배치

web은 /api/v1과 contracts의 생성 타입에 의존한다. api는 ctfm-core와 storage/application service를 호출한다. worker는 같은 queue/storage 구현을 재사용하고 ctfm-core를 실행한다. 현재 queue/storage 구현의 예정 위치는 apps/api/src/ctfm_api/storage이며 설치 가능한 서버 패키지로 worker가 참조한다. core에서 api/worker/web을 import하지 않는다.

계산은 packages/ctfm-core/src/ctfm 아래 measurement, profiles, simulation, adapters로 구분한다. API 서버에서 HTTP 요청 중 장기 연산을 실행하지 않는다. 독립 배포용 서비스 분할이나 여러 DB는 v1에서 필요하지 않다.

runtime 기본 root는 저장소 runtime이며 CTFM_STORAGE_ROOT 환경변수로 재정의한다. API/worker가 동일 root와 DB를 사용한다. 서비스 startup이 uploads/artifacts/db를 생성한다.

## 이전 경로 대응

| 이전 경로 | 현재 위치 또는 구현 대상 |
|---|---|
| simulations/01-r3-inference | 문서는 docs/archive/simulations/, 기능은 core simulation + /simulator |
| simulations/02-model-robustness | 문서는 archive, 모델 비교는 동일 실행기의 실험 축. v1 모델은 MNIST MLP |
| simulations/03-adc-sensitivity | 문서는 archive, ADC 비교는 동일 실행기의 H1/H2 preset |
| shared/ | 문서는 docs/archive/shared/, 공통 계산은 packages/ctfm-core |
| 로컬 ctfm/, pyproject.toml | 보존한 미커밋 참조 구현. 검증 후 core 패키지로 이관 |
| 로컬 configs/mnist-observed.json | 검증 후 configs/experiments/로 이관 |
| 로컬 tests/test_*.py | 코드 이관 시 core tests로 함께 이관 |

원본 폴더의 역사 문서는 삭제하지 않고 archive로 이동했다. 로컬 참조 코드는 새 clone에 없으며 이번 구조 커밋에 포함하지 않는다. 개발자는 필요 시 소유자에게 별도로 전달받아 P1/P2 기준으로 검증한 뒤 코드 커밋한다. 이관 후 import/패키징/pytest 경로와 CLI entry point를 함께 갱신하고 이중 구현을 남기지 않는다.

## 현재 완료 범위와 다음 작업

완료: 디렉터리 골격(.gitkeep), 책임별 README, 기존 문서 archive, 최신 인수인계, 데이터/build 산출물 ignore.

아직 미구현: React 화면, FastAPI 라우트, queue worker, 공유 schema 생성물, 패키지 metadata/lock, 실제 엔진 통합. 빈 폴더를 실행 가능한 앱으로 해석하지 않는다. npm install/dev 또는 서버 실행 명령은 실제 앱 scaffold를 구현·검증한 다음 각 README에 추가한다.

P0에서 packages/contracts의 schema/합성 fixture를 먼저 만들고, 프론트는 apps/web, 백엔드는 apps/api 및 core를 구현한다. 장기 작업 통합은 apps/worker에 배치한다. 상세 인수 기준은 [05-implementation.md](05-implementation.md), 화면/API는 [04-web-api.md](04-web-api.md)를 따른다.
