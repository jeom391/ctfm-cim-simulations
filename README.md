> **2026-09-20 개발 재개:** 구현 전에 [PDF 답변 및 작업 순서](docs/implementation-decisions-2026-09-20.md)와 [설계 v1.2 기준](docs/spec/08-hardware-baseline.md)을 먼저 읽으세요. 문서 결정과 구현 완료는 구분합니다.

# CTFM-CIM Simulations

CTFM 소자의 측정 데이터 분석과 실측 전도도 상태 기반 CIM 추론 평가를 위한 연구용 프로젝트입니다.

## 개발 시작

**최신 확정 설계: [docs/spec/README.md](docs/spec/README.md), 문서·실험 요청 v1.1.0 / Device Profile v1.0.0 (2026-09-18).**

- [측정 분석 계산 규칙](docs/spec/01-measurement-analysis.md)
- [Device Profile 계약](docs/spec/02-device-profile.md)
- [매핑·비이상성·엔진 설계](docs/spec/03-simulation.md)
- [프론트엔드 화면 및 API](docs/spec/04-web-api.md)
- [구현 순서와 인수 기준](docs/spec/05-implementation.md)

홈에서 측정 데이터 분석과 CIM 시뮬레이션을 별도 기능으로 제공합니다. A1~A5를 각각 평가하며, 초기 R3 중심의 세 시뮬레이터 구조는 폐기했습니다. 현재 v1.1 핵심 웹·분석·프로필·PyTorch 시뮬레이션 흐름을 구현했습니다. 실제 MNIST 실행과 합성 소자 프로필을 사용한 검증을 구분하며 원본 측정 검증은 별도입니다.

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

[저장소 구조·이관 안내](docs/spec/06-repository-structure.md)와 [최신 인수인계](handoff/README.md)를 참고하세요. 실행 가능한 React 웹, FastAPI, SQLite queue/worker와 공통 계산 패키지가 연결되어 있습니다. [구현·검증 상태](docs/implementation-status.md), [API 실행](apps/api/README.md), [worker](apps/worker/README.md), [공유 계약](packages/contracts/README.md)을 참고하세요.

## 로컬 실행

Python3.11+, uv, Node22.6+가 필요합니다. 저장소 루트에서:

```sh
uv sync --locked --python 3.11
cd apps/web
npm ci
npm run build
cd ../..
uv run --locked uvicorn ctfm_api.app:app --host 127.0.0.1 --port 8000
```

다른 터미널에서 `uv run --locked python -m ctfm_worker`를 실행한 뒤 http://127.0.0.1:8000 에 접속합니다. API와 worker는 같은 `CTFM_STORAGE_ROOT`를 사용해야 합니다(기본 `runtime/`). 최초 MNIST 실행은 공개 데이터 다운로드가 필요합니다.

```sh
uv run --locked pytest -q
uv run --locked python packages/contracts/export_openapi.py --check
uv run --locked python packages/contracts/export_schemas.py --check
# API/worker가 실행 중일 때 합성 소자 전체 흐름 + 실제 MNIST
uv run --locked python scripts/smoke_workflow.py
```

AIHWKit은 설치와 실제 parity probe를 통과할 때만 노출합니다. C2C/PPA는 최신1차 명세대로 비활성입니다. 원본 A1 데이터 회귀와 검증된 CTFM PPA preset은 아직 확보되지 않았습니다.

### 가속기 엔진 (Linux 전용)

AIHWKit은 공식 PyPI에 **Windows wheel이 없고**(manylinux/macOS만), NeuroSim은 Linux 빌드가 필요합니다.
두 엔진은 별도의 Linux 환경에서만 동작하며, 이 workspace의 Windows 환경은 그대로 유지됩니다.

중요: **AIHWKit 1.1.0은 이 workspace가 lock한 torch 2.14.0+cpu와 호환되지 않습니다.**
2.13 이상에서는 import이 성공한 뒤 C++ 쪽이 텐서 shape을 오독하므로, import 성공을 가용성으로
쓰면 안 됩니다. 실제 호환 범위는 torch 2.10~2.12이며 엔진 환경은 2.12.0+cpu로 고정합니다.
`engine_capabilities()`의 parity probe가 이 경우를 잡아냅니다.

```sh
# WSL/Linux에서 전용 엔진 환경 구성 (/opt/ctfm-engines)
bash scripts/linux/setup_aihwkit.sh          # torch 2.12 + AIHWKit 1.1.0
bash scripts/linux/sweep_torch_abi.sh        # torch ABI 호환 범위 재확인

# 검증
python scripts/linux/probe_aihwkit.py                    # parity probe + 모델 크기 parity
python scripts/linux/verify_aihwkit_adc_combinations.py  # ADC 18조합 대 독립 NumPy
python scripts/linux/e2e_aihwkit_mnist.py                # 실제 MNIST, 두 엔진 대조
python scripts/linux/verify_neurosim_adapter.py          # NeuroSim writer 동일성/실행/preset gate
CTFM_REPO=$PWD bash scripts/linux/e2e_http_engines.sh    # API+worker 전체 HTTP 흐름
```

NeuroSim(DNN+NeuroSim V1.4, CC BY-NC 4.0)은 빌드와 실행이 확인됐으나, 이 빌드는 일부 형상, 특히 좁은 출력
레이어(출력 96 미만)에서 SIGSEGV로 죽습니다. 폭이 균일한 다층 FC는 정상입니다. `mnist_mlp_v1`(784→128→10)은 preset
유무와 무관하게 현재 엔진으로 평가할 수 없으며, adapter가 실행 전에 거부합니다.

## 협업

정민: 분석·알고리즘·백엔드. 유현: 프론트엔드. 소자팀: 물리적 비교 대상과 결과 검토.
작업 브랜치는 codex/ 또는 팀에서 합의한 기능 브랜치를 사용합니다. 명세 변경은 버전과 이유를 남깁니다. 코드 변경은 별도 검증 후 반영합니다.

원본 측정 자료와 실험 산출물은 Git에 포함하지 않습니다. 데이터는 팀 내부에서 별도로 공유하고 파일 해시로 버전을 추적합니다. 기존 docs의 조사 문서와 handoff는 참고 기록이며 docs/spec보다 우선하지 않습니다.
