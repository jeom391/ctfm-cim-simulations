# 실측 C2C·IV/Retention 연결과 통합 마무리 (2026-09-26)

기준: `claude/adc-order-comparison`, 이 작업의 시작 HEAD `453619d`. 결정 근거는 [C2C 추세 보정 결정](c2c-detrending-decision-2026-09-26.md), 분석 코어는 [c2c-measurement-analysis-2026-09-26.md](c2c-measurement-analysis-2026-09-26.md). 상태 표기: **implemented** 코드 존재 · **tested-synthetic** 합성 입력 자동 테스트 · **tested-measured** 실제 측정 파일 실행 · **tested-browser** 실제 브라우저 조작 · **partial** · **blocked**.

## 1. 기능별 상태

| 기능 | 상태 | 근거 |
| --- | --- | --- |
| 실측 C2C 분석(A3 1000회) 코어·CLI | tested-measured | 결정 문서 수치와 일치(3차 상대 편차 Program 0.047767 %, Erase 0.051833 %) |
| C2C 분석 API/worker(kind `c2c_detrended`), `tables.cycles`, 그래프, 결과 해시 고정 | tested-synthetic + tested-measured | `tests/e2e/test_measured_c2c_flow.py`, 실제 HTTP 실행 |
| 실험 요청 schema **1.4.0** `measured_detrended`(서버가 값·provenance 기입) | tested-synthetic + tested-measured | 위조 CV 422, 교차 조건 미확인 422, 변조 감지 422, 1.2.0/1.3.0 의미 유지 |
| 동일 checkpoint C2C off / manual 5 % / measured 실행 | tested-measured | 아래 3절 |
| IV 반복 Vg/Id/Ig 블록 읽기(`layouts.py`), 블록·구간 명시 선택 | tested-measured | 50개 중 49개 읽힘, 팀 Vth 표와 비교(2절) |
| Retention 독립 P/E 시간축 읽기·분석 | tested-measured | 5개 전부 읽힘, 방향별 시간축 적합 |
| D2D (사용자가 고른 두 소자) | tested-synthetic | 실제 두 소자 자동 선택은 하지 않음 — 실측 D2D 실행은 이번에 하지 않음(**partial**) |
| 측정 화면: C2C 탭, IV/Retention 선택기, LTP/LTD 순차 추가·삭제·중복 안내 | tested-browser | 내장 브라우저 패널, 파일은 JS로 주입한 FileList(네이티브 파일 대화상자 아님) |
| 시뮬레이터: C2C 출처 선택(수동/실측 Program), 승인·교차 조건 확인 | tested-browser | 브라우저에서 실행·결과 표시까지 |
| 결과 필드 이름 `mapping_metrics`/`adc_metrics`(+ `mapping_errors`/`adc` 동일 내용 별칭) | implemented + tested | 미생성 진단은 null(빈 성공값 아님) |
| NeuroSim 조건부 PPA 실행 | **blocked** | 4절 |

## 2. 실측 파일 읽기/지원 상태

`scripts/verify_measured_layouts.py --root "<관련 자료>"`가 모든 IV·Retention 파일을 읽고 목록을 만든다. 원본 파일은 커밋하지 않는다(경로 언급만).

- **IV 50개 중 49개 읽힘.** 블록·구간은 항상 사용자가 명시 선택한다(검증 실행에서는 유효 블록 중 최대 진폭, 가장 넓은 상승=Erase / 하강=Program 구간).
  - 읽히지 않는 1개: `A5/_26CTFM_A5_vgid_sweep_225_15V.xlsx` — 12개 블록 뒤 헤더가 `Id, Ig, Vg, Id, Ig`로 어긋나 Vg 열 이름이 하나 빠져 있다(파일 결함). 해결 선택지: 헤더를 바로잡은 사본을 쓰거나 같은 조건의 다른 파일을 선택. 재측정을 기본 해결책으로 요구하지 않는다.
  - 손상 블록: `A3/…_229_15V.xlsx` 블록 0의 셀 하나가 공백 문자열. 손상 블록만 사용 불가로 표시하고 나머지 블록은 사용 가능.
  - `A4/…IdVg_sweep_238_15V.xlsx`의 최대 진폭은 14 V(팀 표의 `238(14V)`와 일치).
  - 팀 `All Device Vth_CCM.xlsx`의 erase Vth와 비교(선형 보간, 1 µA): 비교 가능한 47개 중 **23개가 1e-3 V 이내**, 35개가 0.05 V 이내, 최대 차 0.4547 V. A3·A4·A5는 거의 정확히 일치하고 A1·A2에서 0.005~0.45 V 차이가 난다 — 팀이 다른 블록/방법을 쓴 것으로 보이며 **값을 맞추려고 바꾸지 않았다**. 표: `local_report/evidence/09/measured-file-support.md`.
- **Retention 5개 전부 읽힘.** `Raw Data`의 Erase/Program은 서로 다른 시간축이므로 방향별 시간축으로 적합한다. A1·A2·A4·A5는 2행이 빈 행(건너뜀 기록), A3는 10 s 미만 첫 점 2개를 제외 기록으로 남긴다. `Normalized Data` 시트의 원본 이름(읽기 바이어스, 괄호 번호)은 **참고 기록일 뿐 선택·제외에 쓰지 않는다**. A3·A5의 `(1)`은 R3(1)·R5(1)과 일치하고 R3(2) 파일은 없다. A4는 파일 안 번호가 `(2)/(7)`이라 R4(1)과 내부 번호로는 확인할 수 없어 승인 문서의 매핑에 의존한다.
- C2C: `관련 자료/C2C/_26CTFM_A3_1000Cycle_.xlsx` 한 개(A3). 다른 조건으로 자동 복제하지 않는다.

## 3. 같은 checkpoint의 C2C 실행 결과 (실제 A1 프로필, 실제 A3 C2C 분석)

A1 조합 `combined / fixed_reference`, tile 64, ADC off, 재기록 3회(off는 1회), checkpoint `cc3ba0db…` 하나를 재사용:

| 실행 | ALL 정확도 | C2C 출처 |
| --- | --- | --- |
| off | 0.9641 (재실행 동일) | 없음 |
| manual 5 % | 0.964, 0.9638, 0.9632 | `manual_assumption` |
| measured (Program 0.0478 %) | 0.964, 0.9641, 0.9641 (반복 실행 동일) | `measured_detrended`, 분석 해시 고정 |

정확도 변화는 성공 기준이 아니다. 연결 검증은 적용 계수, provenance, 재현성으로 했다. 측정 편차 0.05 %는 수동 예시 5 %보다 100배 작아 정확도 차이가 거의 없다. A3 분석을 A1 프로필에 쓴 것은 교차 조건을 **명시적으로 확인**한 실행이며(다른 조건에 자동 복제하지 않음) 소자 간 대표성을 뜻하지 않는다. 측정 조건 중 read 단자·VDS·읽기 시간·추출 시점은 미확인이고 소자 ID는 팀이 알려주지 않아 `not provided by device team`으로 기록했다.

## 4. NeuroSim 조건부 PPA — 지원 범위와 막힌 이유

이번 머신(WSL Ubuntu, 사용자 홈)에는 고정된 엔진 checkout(`/opt/ctfm-engines/neurosim`, commit `ac828e67…`)이 **없다**(g++ 13.3.0은 있음). 이전 문서가 다른 환경에서 엔진 실행을 확인했다고 적은 것은 그 환경의 사실이며 이번 머신에서는 재현하지 못했다. 따라서 이번 작업에서 엔진 실행, 64/128 crash 재현, 최소 패치·회귀는 **하지 못했다(blocked)**. 원본 엔진을 새로 내려받아 빌드하는 것은 하지 않았다(출처·설치 승인 없이 외부 코드를 받아 실행하지 않는다).

엔진과 무관하게 확인·정리한 것:

- 승인된 [하드웨어 기준](spec/08-hardware-baseline.md)이 이미 고정한 preset 필드: `technode_nm`=22, `read_voltage_v`=0.55(측정 VDS 0.1 V와 분리), `read_pulse_width_s`=10 ns(가상 read excitation, write pulse 아님), `access_type`=CMOS access, `adc_architecture`=current-mode MLSA, `columns_per_adc`=8, `interconnect`=XY bus, `memcell_type`=RRAM proxy, `input_precision_bits`=8.
- 어떤 승인 문서도 값을 정하지 않은 필드: `cell_bit`, `synapse_bit`(명세는 "bit slicing 없음, 열 수가 늘지 않게"라고만 함), `parallel_rows`, 그리고 요청의 타일 크기와 preset `sub_array`의 대응. 이 값들을 임의로 채우지 않았다.
- 코드의 `preset_decision()`은 아직 `validated_for_ctfm=true`를 요구한다. 명세 §3은 이를 `assumed_proxy`(전도도 전달·회로 구성·누락 항목 검사를 통과한 조건부 추정, `validated_for_ctfm`은 false 유지)로 바꾸라고 하지만, **실험 요청 schema의 `engines.ppa`가 `off`로 고정돼 있고 `_validate`가 PPA를 거부**하므로 API→worker→격리 실행→결과 연결은 schema·API·worker·UI를 함께 바꾸는 별도 작업이다. 엔진 없이 검증되지 않는 게이트 변경은 하지 않았다.
- 미모델링 블록(`analog_subtraction_frontend`, `bipolar_range_conversion`, `digital_subtraction`, `differential_plane_pair`, `per_block_engine_costs`)은 그대로 `missing_components`, 상태 partial, 총계 null로 남는다.

재개 순서: ① 엔진 checkout 확보(경로/획득 방법 확인) → `scripts/linux/verify_neurosim_adapter.py` → ② 64/128 crash 최소 재현·원인 → ③ `assumed_proxy` 게이트와 위 미정 필드 결정 → ④ schema/API/worker/UI 연결 → ⑤ 실제 엔진 1건 실행 비교.

## 5. 남은 사용자 동작·범위

- **네이티브 파일 대화상자 확인**: 브라우저 검증은 실제 `<input type=file>`에 파일을 주입해 React 핸들러가 동작하는지 확인한 것이다. OS 파일 선택 창 자체는 자동화하지 못했다. 사용자가 `/measurements`의 "측정 파일 추가"로 파일을 직접 선택해 같은 흐름(C2C 탭 → 조건 입력 → 분석)을 한 번 확인하면 마무리된다.
- 실측 D2D(사용자가 고른 두 소자)와 실측 Retention의 프로필 연결·시뮬레이터 실행은 이번에 하지 않았다.
- C2C 측정 조건 4개(read 단자 의미·VDS·읽기 시간·추출 시점)와 실제 소자 ID는 소자팀 확인 후 입력. VDS 없이는 절대 전도도 변환 불가.
- 잔차 시간 상관(lag-1 0.6~0.7)은 독립 무작위 샘플링이 재현하지 않는다. 분석 결과는 순수 C2C가 아니다.
