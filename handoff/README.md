> **최신 인수인계 (2026-09-20):** 팀 구현은 main 57af5ec에 반영됐습니다. 아래의 초기 골격/미구현 상태 설명은 당시 기록입니다. 먼저 [두 PDF 답변·작업 순서](../docs/implementation-decisions-2026-09-20.md) → [하드웨어 기준 v1.2](../docs/spec/08-hardware-baseline.md) → [근거·보고서 기준](../docs/research/hardware-baseline-evidence.md)을 읽으세요. 충돌 시 새 문서가 우선하며 코드/schema는 별도 이행이 필요합니다.

# 최신 개발 인수인계

전체 계산·API 설계는 v1.0.0이며 통합 웹 저장소 구조를 v1.0.1로 갱신했습니다. 기존 세 시뮬레이터를 각각 구현하지 않고 단일 웹 앱과 공통 실험 실행기를 사용합니다.

## 먼저 읽을 문서

1. [개발 시작](../docs/spec/README.md)
2. [통합 저장소 구조·이관표](../docs/spec/06-repository-structure.md)
3. [화면·API 계약](../docs/spec/04-web-api.md)
4. [구현 순서와 검증 기준](../docs/spec/05-implementation.md)

## 담당별 시작 위치

- 프론트엔드: apps/web. 홈, /measurements, /simulator 페이지.
- API: apps/api. 업로드·분석·프로필 발행·실험·작업 API.
- 계산/엔진: packages/ctfm-core. 측정/프로필/매핑/비이상성/adapter.
- 장기 작업: apps/worker. queue 처리·진행률·취소.
- 공동 계약: packages/contracts. P0에서 OpenAPI/JSON Schema/합성 fixture 생성.

## 완료와 남은 작업

저장소 골격, 파트별 README, 구조 명세, 이전 문서 archive 이동을 완료했습니다. 현재 폴더는 구현 시작용이며 실행 가능한 웹/API를 만들었다는 뜻은 아닙니다. 기존 루트 ctfm/ 및 초기 설정/테스트는 로컬 미커밋 참조 구현으로 보존했고 이번 배포에는 포함하지 않았습니다. 검증 후 core 패키지로 이관합니다.

개발은 P0 계약/환경 → P1 분석 → P2 프로필·기준 추론 → P3 비이상성 → P4 엔진 → P5 웹 통합 순서입니다. 프론트는 P0 합성 계약으로 먼저 작업할 수 있습니다. 원본 측정 파일·runtime DB·실험 결과는 Git에 올리지 않습니다.

01_current-design-handoff.md는 과거 기록입니다. 본문의 이전 경로나 구현 중지 지시보다 현재 docs/spec를 우선하세요.

## ADC·NeuroSim 후속 정정 (문서 v1.0.2)

ADC bits/배열 크기는 사용자가 선택하는 실행 입력이며 추천 preset 수치를 고정하지 않는다. [설정 검토](../docs/neurosim-user-controls-review.md)를 확인한다. upstream SRAM 기본 설정 또는 0.1 V 단순 대입으로 CTFM PPA를 구현하지 않는다. 실제 등가 회로/전압 모델 검증 전 PPA는 unsupported이고 정확도 실험은 별도로 진행한다. SAR/MLSA·공유 ADC·노드 등은 검토된 추가 후보이며 아직 API 지원 완료가 아니다.

## 현재 착수 기준: v1.1.0

[1차 사용자 선택 명세](../docs/spec/07-first-release-controls.md)를 추가로 읽는다. ADC on/off·3~8 bit·타일 64/128/256, 풀/매핑, D2D 반복, Retention 연수를 실행 입력으로 연결한다. [공유 계약](../packages/contracts/README.md)에 schema와 합성 예시·검증 명령이 있다. schema_version=1.1.0이며 과거 실험 요청 shape보다 우선한다. 검증기는 inference를 수행하지 않는다. 개발 담당은 form→API→resolved config→실행기→결과의 선택값 일치와 실제 중간 계산 변화를 테스트한다. C2C 및 PPA는 아직 비활성화한다.
