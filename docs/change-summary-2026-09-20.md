# v1.2 변경 요약 — 무엇을 구현했나

2026-09-20 · 브랜치 `codex/p0-api-contracts`, `69d3423` 다음에 올린 변경 묶음입니다.

규모: 수정 **29개 파일 +2,004 / −477**, 신규 **4개 파일 1,020줄**.

## 신규 파일

| 파일 | 줄 | 내용 |
|---|---|---|
| `packages/ctfm-core/src/ctfm/adapters/neurosim_build.py` | 325 | 설정별 격리 빌드·캐시 (결정 C1) |
| `packages/ctfm-core/tests/test_neurosim_build_and_cost.py` | 480 | 빌드 캐시 + 회로 집계 + 합성 규칙 테스트 |
| `scripts/linux/repro_neurosim_crash.py` | 153 | crash 최소 재현(이분법 축소) |
| `scripts/linux/probe_neurosim_crash_boundary.py` | 62 | crash 경계 측정 |

## 기능별로 무엇이 들어갔나

### 1. 정확도 모델을 v1.2로 교체 — 가장 큰 변경
`simulation/math.py`, `simulation/torch_runner.py`, `simulation/__init__.py`

- **입력 unsigned 8bit bit-serial**: `q=clip(floor(255x/r+0.5),0,255)`, LSB부터 고정 8 cycle,
  전부 0인 cycle도 skip하지 않음. r은 픽셀 1 / hidden은 디지털 checkpoint의 validation 5k
  ReLU 최댓값.
- **G+/G− 두 plane 유지**: 이전에는 `scale*(G+ − G−)` 단일 행렬로 합쳐 계산했습니다.
  이제 tile마다 `p+`, `p−`를 각각 계산합니다. 부분합 단위는 지멘스×입력 bit이며 물리 전류는
  여기에 VDS를 곱한다는 사실을 결과에 기록합니다.
- **두 ADC 순서**: `subtract_then_adc`는 `p+−p−`를 `[-R,R]`에서, `adc_then_subtract`는
  각각 `[0,R]`에서 양자화 후 차감. 양자화는 **bit plane마다** 수행하고 2^k를 곱해 합산.
- **ADC 범위 보정**: nominal M0에서 ADC를 우회한 경로로 한 번에 두 순서의 범위를 모두 수집
  (순환 보정 없음). bit 수·배열·시간점 사이에서 공유.
- **D1 실행 추가**: 디지털 가중치 + 8bit 입력. FP32 → 입력 양자화 → 매핑 → ADC 손실을 분리.

검증: 손계산 fixture(2입력 1출력), **ADC off에서 bit serial == 8bit 복원 direct MAC**
(NumPy·torch 양쪽), 3~8bit × 64/128/256 × 두 순서 36조합을 독립 NumPy 모델과 대조.

### 2. 실행 계약 1.2.0
`packages/contracts/*`, `apps/api/src/ctfm_api/*`, `apps/web/src/lib/*`

- `schema_version` 1.2.0, `hardware.adc_order` 추가 (ADC off에서는 null = 적용 안 됨)
- **`tile_size`는 ADC 여부와 무관하게 항상 명시** — 물리 배열 크기이므로. 1.1의 `tile=null`
  관례를 유지하지 않음
- 1.1.0 요청은 재해석하지 않고 `schema_migration_required`로 거부
- OpenAPI / JSON Schema / TypeScript 재생성, capabilities에 `adc_orders` 노출
- `validated_combinations`에 `adc_order` 포함 — 한 순서에서 검증된 조합이 다른 순서에서
  통과하지 않음

### 3. NeuroSim 격리 빌드·캐시 (결정 C1)
`neurosim_build.py` (신규)

- key = upstream commit + patch hash + resolved config + compiler/version/flags + target platform
- 임시 디렉터리 빌드 → **단일 rename으로 원자적 등록**, 같은 key 동시 빌드는 디렉터리 lock
- 패치된 소스를 **다시 읽어** 요청과 다르면 실패
- **실제 `Param.cpp`에 맞춰 작성**: 생성자는 `param->levelOutput = …`이 아니라 bare 대입
  (`levelOutput = 32;`)을 씁니다. 처음 작성한 정규식은 실제 파일에서 하나도 매칭하지 못했을
  것입니다. 16개 필드를 실측 대조로 확정했습니다.
- 엔진 파생값(`parallelRead`, `readVoltage`, `numRowParallel`, `dumcolshared`)은 패치하지 않고
  기록 — 생성자가 덮어쓰므로 쓰면 무효
- 조건부 재대입 검사: `cellBit`은 SRAM에서 1로 강제되므로, 그 조건이 성립하는 설정은 **빌드 거부**
- `ppa_result`가 실행 전 설정별 바이너리를 빌드/캐시에서 가져와 그것을 실행. 빌드 실패는
  `failed`로 드러나고 참조 바이너리로 조용히 되돌아가지 않음

### 4. 차단 사유와 미완 사유 분리 — 숨어 있던 버그
`neurosim.py`

이전에는 `DIFFERENTIAL_PLANE_UNRESOLVED`가 `reasons`에 무조건 들어가서 **엔진 실행 자체가
영원히 막혀** 있었습니다. 빌드 연결도 도달 불가 코드였습니다. 이제:

- `blocking_reasons` — preset 미승인, 엔진 미빌드, crash 형상 → 실행 안 함
- `incomplete_reasons` — 비용 모델 없는 블록 → 실행은 하되 **총계만 null**

### 5. 회로 집계와 비용 coverage
`neurosim.py`

- `circuit_inventory`: 물리 셀 `2·R·C`, plane당 가중치 1 셀(bit slicing 없음), 타일/plane별
  ADC 수, 추론당 변환 cycle. `adc_then_subtract`는 plane마다 변환기가 필요하고
  `subtract_then_adc`는 차감 후 하나 → **같은 bit 수라도 ADC 수가 다름**
- `compose_differential_cost`: per-plane 블록은 두 plane 합산, shared 블록은 1회,
  지연 = `max(plane) + 공통 누산·차감`. **전체 2배 금지**를 테스트로 고정
- `cost_coverage`: 상태 `partial`, 총계 **null**, 누락 블록을 이름으로 보고,
  쓰기 datapath 등은 `excluded_by_scope`로 별도 표시

### 6. 1 ms 일괄 거부 → 출처 검사 (결정 A7)
`neurosim.py`

쓰기 펄스로 표기된 출처나 선언된 `write_pulse_width_s`와 같은 값은 크기와 무관하게 거부,
읽기로 출처가 명시된 1 ms는 허용. `read_pulse_width_source`를 필수 필드로 추가.
10 ns 가정 대비 settling/ADC 시간 검사는 `schedule_feasibility`로 분리하고, 비교할 값이 없으면
**`not_performed`** 으로 보고(‘feasible’로 위장하지 않음).

### 7. A1 인수 조건을 행 번호 검증으로 교체 (결정 D1)
`tests/test_measured_a1_regression.py`

개수 검사(1024 전환 / 1022 상태) → **행 번호 관계 검사**(전환 행 j → 읽기 행 j-2). 개수는
파일별 provenance이므로 환경변수 지정 시에만 단언.

**기존 결함 2건 수정**: `source_rows` 미전달, 열 매핑 키 오타(`columns=`). 실제 A1 파일이
왔어도 그대로는 실행되지 않는 상태였습니다.

### 8. crash 규칙 정정 — 기록이 틀려 있었음
`neurosim.py`, `scripts/linux/*`

엔진 호스트(WSL)에서 실제로 측정한 결과:

- **"출력 96 미만은 모두 crash"는 틀림.** `128×10`, `256×10`, `1024×10`, `256×64` 모두 완주.
  기존 `MIN_SAFE_OUT_FEATURES=96` 가드가 **실제로 도는 형상을 거부**하고 있었습니다.
- **"mnist_mlp_v1은 평가 불가"도 틀림.** subArray **256에서 완주**합니다. 이전 스윕이 이
  형상에 64/128만 시도했습니다. 배열 크기가 결정 요인이며 스톡 바이너리도 256에서 완주합니다.
- crash는 fan_in에 단조롭지 않음(257·260·320 crash, 512 완주, 784 crash)

`topology_support(layer_dims, sub_array)`가 측정된 `(형상, subArray)` 쌍만 거부하도록
바꿨습니다. preset의 `sub_array`가 요청 배열과 다르면 차단합니다(다른 회로의 비용이 되므로).

### 9. 입력 인코딩 차이를 수치로
`neurosim.py`

NeuroSim FC trace는 signed two's complement라 **비음수 신호는 격자의 절반만** 사용 →
8bit trace가 실효 **7bit**(128레벨), 정확도 경로는 256레벨. 레이어별 실효 bit·최대 오차를
측정해 결과에 싣습니다. `decode_activation_planes()`로 인코더를 역변환해 왕복 오차 ≤ 1 LSB 확인.

### 10. 프론트
`apps/web/src/*`

두 ADC 순서 라디오 선택, 08 §6의 한 줄 설명을 툴팁이 아닌 **항상 보이는 문구**로 배치,
같은 bit 수가 같은 비용을 뜻하지 않는다는 문장 병기. PPA 패널에 조건부 추정 라벨·물리 구성
표·누락 블록 표·범위 제외 항목·엔진 총계(전체 PPA 아님)·읽기 구간 검사 결과 표시.
차단 사유와 미완 사유를 구분해 보여줍니다.

### 11. 문서
`docs/implementation-status.md`에 v1.2 구현·후속 작업·엔진 실측 절을 추가하고, 반증된 두
단락에 정정 주석을 달았습니다(삭제하지 않음).
`docs/구현한것-2026-09-20.md`, `docs/구현못한이유-2026-09-20.md` 신규.

## 검증

| 대상 | 결과 |
|---|---|
| Windows `uv run --locked pytest -q` | **241 passed, 5 skipped** (이전 기준 159) |
| 웹 `tsc --noEmit` / `npm test` / `npm run build` | 통과 / 13 passed / 통과 |
| WSL: Param.cpp 16개 필드 패치 왕복 | 불일치 0 |
| WSL: 실제 g++ 13.3 빌드·캐시 | 첫 빌드 3.9초, 재요청 캐시 히트 |
| WSL: mnist_mlp_v1 subArray 256 | 완주, 3회 재실행 동일 |
| WSL: ADC 3/5/8 bit | ADC 면적 3.09e-8 / 6.35e-8 / 3.77e-7 m² — 설정이 실제로 회로를 바꿈 |

skip 5건은 모두 원본 A1 파일 미제공입니다.

## 커밋 구성

계약과 정확도 모델은 서로를 필요로 해서(요청 1.2.0을 `_validate`가 검사하고, 그 검사를 e2e가
지나갑니다) 한 커밋으로 묶었습니다. 나머지는 기능 단위로 나눴습니다.

1. `fix(measurement)` — A1 행 번호 인수 조건 + 기존 결함 2건
2. `feat(engines)` — 격리 빌드·캐시, 1 ms 출처 검사, 회로 집계·합성 규칙·coverage,
   차단/미완 사유 분리, crash 규칙 정정
3. `feat(core)` — 실행 계약 1.2.0 + v1.2 정확도 모델 (8bit bit-serial, 두 plane, 두 순서)
4. `feat(web)` — 순서 선택 UI + PPA 패널
5. `docs` — 상태·구현한것·구현못한이유·변경요약

전체 트리에서 **241 passed, 5 skipped**를 확인했습니다. 중간 커밋 각각을 따로 돌려보지는
않았습니다.
