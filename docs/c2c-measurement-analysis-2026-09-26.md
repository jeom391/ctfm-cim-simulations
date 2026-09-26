# 실측 C2C 분석 코어 구현 (2026-09-26)

결정 근거: [추세 보정 결정](c2c-detrending-decision-2026-09-26.md). 이 문서는 구현 범위만 기록한다. **웹/API/프로필 스키마/시뮬레이터 연결과 NeuroSim은 포함하지 않는다.** 기존 수동 C2C(`manual_assumption`) 경로와 `ctfm.measurement.analyze()`는 변경하지 않았다.

## 사용

```sh
python scripts/analyze_c2c.py --file <_26CTFM_A3_1000Cycle_.xlsx> --condition-id A3 \
    --out result.json --plot result.png [--condition program_voltage_v=10 ...] [--no-series]
python -m pytest packages/ctfm-core/tests/test_measurement_c2c.py -q
```

원본 A3 워크북은 저장소에 없다. 테스트는 `CTFM_A3_C2C_FILE` 또는 루트 `관련 자료/C2C/`의 파일이 있을 때만 실측 비교를 실행하고(SHA256 고정), 없으면 skip한다. 합성 테스트는 항상 실행된다.

## API (`packages/ctfm-core/src/ctfm/measurement/c2c.py`)

- `analyze_c2c_file(bytes, filename, sheet=None, device_id=None, condition_id=None, measurement_conditions=None)` → dict. 기존 `parse_table`(크기 제한·수식 캐시 검사 포함)을 재사용한다.
- `analyze_c2c(table, filename=..., sha256=..., ...)` — 이미 파싱된 표 입력. 입력은 수정하지 않는다(deepcopy).
- 실패: `C2CAnalysisError.issues = [{code, detail}]`. 코드: `missing_column`, `ambiguous_header`, `unit_mismatch`, `missing_value`, `non_numeric`, `non_finite`, `non_integer_cycle`, `duplicate_cycle`, `cycle_gaps`, `too_few_cycles`, `unknown_condition_field`, `sheet_not_selected`.

## 계산 정의

헤더로 열을 찾는다(`Cycle`, `Program_Id_<u>`, `Erase_Id_<u>`, 선택 `Erase_minus_Program_<u>`, u∈{A,mA,uA,nA}). 행 수·파일명으로 조건을 정하지 않는다. 빈 후행만 제외(개수 기록), 그 외 결측·중복·비유한·간격은 오류로 거부하고 삭제하지 않는다. 역순 입력은 회차로 정렬하고 경고한다(원본 행 번호 보존).

Program/Erase 각각: `x=2(n−n_min)/(n_max−n_min)−1`, `numpy.linalg.lstsq`(SVD)로 3차 OLS `T(n)`, `r=I−T`, `z=r/T`, `relative_residual_std_percent=100·std(z, ddof=1)`. 모든 `T>0`이 아니면 해당 분기는 `status: blocked`이고 상대 편차를 내지 않는다. 외삽 없음. D열은 `Erase−Program` 검산(`difference_check`)에만 쓰며 통계에 넣지 않는다.

진단: 1~4차 민감도(계수·상대 표준편차·lag-1), 4차/3차 변화율, 100회 구간별 평균 잔차·상대 표준편차(데이터 있는 구간만, 2점 미만은 `null`+사유), 3차 잔차 lag-1(정의 불가 시 `null`+사유), 원본 전체 통계(평균·std·상대 std·min/max).

결과에는 메서드, 계수와 기저, 원본 SHA256, 시트·헤더, 단위와 A 환산 계수, 회차 범위·개수·원본 행 범위, 측정 조건 9개 필드(사용자가 `measurement_conditions`로 준 값만 `confirmed:true`, 나머지는 `null/false`, LTP/LTD에서 복사하지 않음), 경고를 기록한다. `is_pure_c2c_iid_estimate`는 항상 `false`. `simulator_use`: 후보는 Program뿐(`approved_for_simulator:false`), Erase는 `analysis_only`이며 평균·G+/G− 대응·소자 간 복제 필드는 없다.

## 다음 연결에 필요한 계약 변경 (이번에 하지 않음)

분석 결과를 참조하는 profile/실험 요청 필드(`source:"measured_detrended"` 등)와 schema 버전, 사용자 승인 상태 저장, 기존 `manual_assumption`과의 구분, 결과 provenance 노출, 웹 업로드·그래프 화면.
