# Device Profile 계약

버전 `1.0.0` · [개발 시작](README.md)

## 생명주기

`analysis succeeded -> draft profile -> 사용자 검토 -> published revision`. 발행된 revision은 불변이다. 수정은 새 revision을 생성한다. 실행은 최신값을 따라가지 않고 정확한 revision/hash를 고정한다. 분석 완료가 자동 발행을 뜻하지 않는다. 공통 구간 수치가 아직 없다는 이유로 미검증 팀 수치를 채우지 않는다.

단일 JSON manifest와 상태 CSV를 export/import하는 ZIP을 사용한다. ZIP에는 manifest, 참조 표와 SHA256만 담고 원본은 기본 제외한다. ZIP import는 경로 탈출을 차단하고 해시·스키마를 검증한다. 단위는 모두 SI, null은 미제공/산출 불가이며 NaN/Infinity는 허용하지 않는다.

## 필수 필드

| 필드 | 형식·의미 |
|---|---|
| schema_version | `1.0.0` |
| profile_id, revision, profile_hash | UUID, 양의 정수, canonical JSON 및 상태 파일 SHA256 기반 식별 |
| condition_id, display_name | A1~A5 또는 사용자 식별자, 표시명 |
| status, created_at, published_at | draft/published, UTC ISO8601 |
| measurement | vds_v=0.1, read_vgs_v=0, pulse_width_s=0.001, interval_s=0.001, applied_pulse_count=512, saturation_verified=false |
| sources | file_id, sha256, filename, sheet, columns, units, device_id, condition_id |
| extraction | parser 버전, 전체 임계값, start_time_s=6, sample_offset_rows=2, 제외 목록 |
| states_file, states_sha256 | 아래 상태 CSV 참조 |
| pools | 풀별 state_ids, available, reason, g_min_s, g_max_s, common_lo_s/common_hi_s |
| d2d | status=available/unavailable, cv 또는 null, analysis_id, source_kind=iv_proxy, physical_device_count=2, matched_conditions, assumption_ids |
| c2c | status=unavailable, cv=null, reason=not_provided |
| retention | status, analysis_id, source_label, vds_v, read_vgs_v, program_fit/erase_fit의 a,b,RMSE,R²,N,time_min_s,time_max_s |
| assumptions | ID, 설명, evidence_kind=measured/derived/assumed, source_ref |
| review | 검토자 표시명, 검토 시각, 채택/제외 사유 |

상태 CSV: `state_id,source_id,source_row,transition_row,time_s,direction,pulse_step,extraction_index,id_a,vgs_v,conductance_s,selected,exclusion_reason`. state_id는 파일 해시·시트·행·추출규칙 버전에서 안정적으로 생성한다. 같은 수치 G에 여러 state_id가 있을 수 있다. `selected=false`인 표본을 삭제하지 않는다.

## 발행 검증

- 같은 프로필에 서로 다른 A조건·읽기 바이어스의 펄스 상태를 섞지 않는다.
- 선택 상태 G는 유한·양수여야 하며 ID/VDS와 수치 일관성이 있어야 한다.
- 최소 하나의 풀이 서로 다른 G 2개 이상이어야 한다. 개별 풀의 실패는 다른 풀을 막지 않는다.
- Gmin/Gmax는 목록에서 계산하며 수동 입력으로 확장할 수 없다.
- D2D가 없으면 baseline 프로필 발행은 가능하다. D2D 실행만 차단한다. Retention도 동일하다.
- Retention Program의 I_fit(10 s)>0을 시간 시뮬레이션 사용 전에 검증한다.
- 자동 노이즈 필터·사용자 제외가 있다면 버전과 사유를 기록한다. 가정은 프로필 상세와 결과에 노출한다.

## 데이터 경계

시뮬레이터는 발행 프로필만 읽으며 원본 곡선을 재해석하지 않는다. 상태의 수치 G와 도달 경로는 구분한다. 동일 state_id를 양방향 공통 물리 상태의 증거로 사용하지 않는다. 프로필 간 비교는 별도 실행이며 소자별 최소/최대 전도도 차이를 보존한다.
