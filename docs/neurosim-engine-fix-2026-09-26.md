# NeuroSim 실패 원인 추적과 엔진 수정 (2026-09-26, 작업 11)

증거: `local_report/evidence/11/`. 패치: `engine-patches/neurosim/0001-…patch`(+README). 원본 엔진 `~/ctfm-engines/neurosim`(commit `ac828e6`)의 소스는 수정하지 않았다(소스 해시 동일 확인). 작업은 그 checkout을 복제한 `neurosim-fix`(브랜치 `ctfm-fix`)에서 했고 깨끗한 복제 `neurosim-fixed`(commit `b383172`)를 실행 엔진으로 쓴다.

## 1. 정정: 작업 10의 원인 설명은 틀렸다
작업 10은 “가장 넓은 층 column 수 ≥ 4×subArray”(conventional mapping 검사)를 모든 실패의 원인으로 적었다. gdb(-g -O0)로 배열별 실제 설정을 보면 이 빌드는 `novelMapping=1`(Param.cpp 기본값, 어댑터가 바꾸지 않음), `markNM={1,1}`(두 층 모두 novel mapping)이며 검사는 novel 분기의 `maxPESizeNM < 2*numRowSubArray`다. 실패는 서로 다른 두 원인이다 (`trace-configs-before.json`).

| 경우 | maxPESizeNM | 엔진 메시지 | 종료 | 원인 |
| --- | --- | --- | --- | --- |
| proxy(spec 08) 32, 64 | 128 | 없음 | SIGSEGV | **A. 타일 분할 결함** (`CopyPEArray`가 112행 배열에서 128행을 읽음) |
| proxy 128, 256 | 128 | “SubArray Size is too large …” | SIGSEGV | **B. 계층 제약** 뒤의 널 역참조 |
| stock SRAM 64, 128 | 1024 | 없음 | SIGSEGV | A (196행 배열에 256행, 392에 512) |
| stock 256, 합성 768→512→64 @64 | — | — | 정상 | 행 수가 PE 크기의 배수이거나 타일이 하나 |
| 합성 768→512→64 @128, 784→512→10 @64 | 512 | 없음 | SIGSEGV | A |

### A. 타일 분할 결함 (수정함)
`Chip.cpp ChipCalculatePerformance`의 novel-mapping 분기는 `numRowMatrix = min(PE, 남은 행)`, `numColMatrix = min(PE, 남은 열)`(PE 크기 조각, 마지막은 부분)을 `TileCalculatePerformance`에 알려 주고 타일을 `i*PE`에서 시작시키면서, 넘겨주는 배열은 `차원 / 타일 수`(정수 나눗셈)로 만든다. 784행·PE 128이면 7타일이므로 배열은 112행인데 엔진은 128행을 읽는다. 두 값은 차원이 PE 크기의 배수이거나 타일이 하나일 때만 같다(그래서 stock 256, 768행은 정상). 수정: `numPENM==1`(모든 완전연결층)에서 배열 크기를 `numRowMatrix × numColMatrix`로 한다. 합성곱(`numPENM>1`)은 검증 자료가 없어 원래 식을 그대로 둔다(미검증 범위).

### B. 계층 제약 (수정하지 않음, 검사 유지)
novel mapping은 PE를 2×2 subArray 이상으로 요구한다. 128 column 층은 subArray 128/256에서 그 PE를 만들 수 없다. 엔진이 의도한 제약이며 결함이 아니므로 검사를 지우거나 우회하지 않았다. 다만 메시지 뒤에 계속 진행해 빈 vector를 역참조하던 것은 결함이라 `exit(-1)`로 끝나게 했다(검사는 유지, 종료가 깨끗해짐).

## 2. 검증
- **회귀**(`validation.json`, `stdout/`): 참조 엔진이 성공하던 경우(stock 256, 합성 768@64)는 stdout이 바이트 단위로 같다. 참조가 SIGSEGV이던 6개는 완료, 128/256(proxy)은 엔진 메시지와 함께 rc 255.
- **부분 타일 상한**(`partial-tile-bound.json`): 같은 데이터로 768/896행(수정 전후 동일) 사이에 784행(참조는 크래시, 수정본 완료)의 ADC·읽기 에너지가 놓인다.
- **어댑터 규칙**: `hierarchy_problem`을 엔진의 실제 novel 규칙으로 고쳤다(widest ≥ 2×subArray). `topology_support`의 측정 크래시 표는 참조 엔진만 설명하며 패치된 엔진(`engine_fixes`가 `Chip.cpp`에서 마커를 읽어 판정)에는 적용하지 않는다.
- **물리적 타당성**(엔진 종료 코드 0과 구분): `engine_cross_check`. “Chip total CIM array”를 셀 발자국(4F×12F, 22 nm)으로 나누면 131,072셀/plane이 정확히 나온다(8타일×128×128). 가중치는 101,632개, 명세 타일링(64×64 논리 타일)은 114,688셀이다. 엔진은 PE 크기로 패딩하므로(가중치 활용 77.5 %) 명세 목록과 다르고, 이를 `model_mismatches`의 `array_cell_count`로 표시한다. 엔진은 plane 하나만 세므로 총계는 여전히 null이다.
- **실제 MNIST 경로**(`ppa-fixed-engine-A1.json`): A1 프로파일, 요청 tile 64, 두 ADC 순서, 학습된 checkpoint 활성 trace. `ppa.status=partial`, `model_status=assumed_proxy`, 공개 area/energy/latency는 null, `engine_totals`(area 1.265e-06 m², 에너지 2.748e-09 J/추론, 지연 9.42e-07 s)는 누락 블록이 있어 총계가 아니다. 두 ADC 순서의 엔진 값이 같다: 엔진은 순서를 모델링하지 않으며(`adc_order` mismatch) 순서별 ADC 수(212/424)는 어댑터 산술뿐이다.
- 지원 배열 크기(mnist_mlp_v1, spec 08 preset): **64만**. 128/256은 B로 거부되고 32는 요청 enum에 없다.

## 3. 아직 열려 있는 것
1. subArray 128/256에서 mnist_mlp_v1을 비용 산정하려면 엔진의 PE 최소 크기 제약을 바꾸는 모델링 결정이 필요하다(층 폭 확대·bit slicing·엔진 계층 모델 변경은 설계 결정이며 채택하지 않았다).
2. 합성곱 층(`numPENM>1`)의 분할은 수정·검증하지 않았다(mnist_mlp_v1은 해당 없음).
3. ADC 개수·스케줄·두 plane·공유 블록 비용은 엔진 출력으로 검증할 수 없어 누락 블록으로 남는다. 입력 인코딩 차이(비음수 활성이 부호 격자의 절반만 사용, 유효 7 bit)는 기존 측정값 그대로 결과에 실린다.
4. ADC 면적이 subArray 32와 64에서 약 2배 차이 나는 이유(열 수/8로 ADC 수가 같아야 하는데)는 확인하지 않았다.
