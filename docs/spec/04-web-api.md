# 웹 화면과 API 계약

버전 `1.0.0` · [개발 시작](README.md)

## 구현 위치

단일 웹 앱은 apps/web, FastAPI는 apps/api, 장기 작업은 apps/worker에 둔다. 페이지는 /, /measurements, /simulator로 나눈다. [전체 저장소 구조](06-repository-structure.md)를 따른다.

## 구현 구조

프론트엔드 React+TypeScript, 백엔드 Python FastAPI, 단일 Linux 실행 worker로 시작한다. SQLite에 메타데이터/작업 상태, 서버 관리 디렉터리에 업로드와 artifact를 저장한다. API는 장기 학습을 request thread에서 실행하지 않는다. 분석·실험 작업을 DB queue에 넣고 worker가 처리한다. 모델/엔진 실행은 worker subprocess로 격리한다. v1은 팀 로컬 또는 접근 제한된 내부 배포이며 공개 인증·다중 조직 서비스는 범위 밖이다.

## 화면

홈: 측정 분석, CIM 시뮬레이션, 최근 작업.

측정 분석: Vth/MW, D2D, Retention, LTP/LTD 상태 추출 탭. 업로드 → 시트/열·단위 미리보기 → 비교 소자/조건 확인 → 계산 → 결과/제외 사유 → 다운로드. 상태 추출 결과에서 프로필 초안 생성, 선택 상태·D2D·Retention 결과 연결, 가정 확인 후 발행한다. Vth/MW는 프로필 필수 입력이 아니다.

CIM: 발행 프로필 revision·지원 모델·풀/매핑·효과·반복·years·하드웨어 preset 선택 → 요약 → 실행 → 진행률 → D0/M0 대비 결과. 미제공 D2D/Retention은 해당 옵션 비활성화, C2C는 “현재 데이터 미제공, 미반영”으로 고정 표시한다. common unavailable은 “공통 범위 없음”으로 설명하고 프로필 전체를 사용 불가로 만들지 않는다.

결과 화면에서 측정값/계산값/가정, Retention 외삽, 엔진 상태, 정확도와 PPA의 모델 차이를 보여준다. 아직 없는 값에 예시 정확도를 실제 결과처럼 넣지 않는다. 구현 상세인 파일 절대 경로·stack trace는 기본 화면에 노출하지 않는다.

## 공통 계약

prefix `/api/v1`, JSON UTF-8, 시간 UTC ISO8601, id UUID. SI 단위. 응답 오류는 `{error:{code,message,field,details,request_id}}`. 미제공 값 null, 불가능 사유 reason, warnings 배열을 사용한다. 숫자 오류를 문자열 'NaN'으로 내보내지 않는다.

업로드는 multipart, 파일당 최대 100 MiB, 요청 최대 20개다. 확장자/내용·ZIP 크기·파서 제한을 검증하고 사용자 파일명을 저장 경로로 사용하지 않는다. 분석 결과의 파일 ID로만 접근한다. CSV/XLSX export의 사용자 문자열은 수식 실행을 방지한다.

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| GET /capabilities | 없음 | 모델, 엔진 available/version/reason, 효과·지원 형식 |
| POST /files | multipart files | 201, file_id/name/hash/size/type 목록 |
| GET /files/{id}/preview | sheet 선택 query | 시트·열·단위 후보·최대 50행, detection warnings |
| POST /analyses | kind, inputs, settings | 202, analysis_id, job_id |
| GET /analyses/{id} | 없음 | status, kind, settings, summaries, table/plot artifacts, exclusions |
| POST /profiles | condition_id, state_analysis_id, d2d_analysis_id?, retention_analysis_id?, selected_state_ids | 201, draft profile |
| GET /profiles | status 필터 | 프로필 목록과 revision |
| GET /profiles/{id}/revisions/{rev} | 없음 | 전체 manifest |
| POST /profiles/{id}/revisions | base_revision, 변경사항 | 201, 새 draft revision |
| POST /profiles/{id}/revisions/{rev}/publish | reviewer, review_note | 200, 검증한 published manifest |
| GET /profiles/{id}/revisions/{rev}/export | 없음 | manifest+states ZIP |
| POST /profiles/import | multipart ZIP | 검증 후 201 draft, 원 revision 출처 보존 |
| POST /experiments | 아래 실행 설정 | 202, experiment_id, job_id |
| GET /experiments/{id} | 없음 | 설정, status, 결과 artifact IDs, 요약 |
| GET /jobs/{id} | 없음 | state, stage, progress, completed/total, timestamps, error |
| POST /jobs/{id}/cancel | 없음 | 202, cancel_requested |
| GET /artifacts/{id}/download | 없음 | 관리된 artifact 파일 |

`analyses.kind`: iv, d2d, retention, pulse_states. inputs는 file_id/sheet/column_mapping/units/device_id/condition_id와 branch/sweep 선택을 포함한다. settings는 측정 명세의 모든 계산 기본값을 서버에서 확장한 뒤 결과에 그대로 반환한다. d2d는 물리 소자 2개, pulse_states는 방향별 파일, retention은 Raw Data 열을 요구한다. client는 서버 결과와 별도로 수식을 재구현하지 않는다.

실험 요청: `schema_version, profile_refs[{id,revision}], model_id, checkpoint_id|null, pools[], mappings[], effects{d2d,retention,adc}, years[], arrays, seed, hardware{tile_size,adc_bits,preset_id}, engines{accuracy,ppa}`. baseline 기본은 combined/fixed_reference, effects 모두 false, arrays=1, years=[0], accuracy=torch_reference, ppa=off다. D2D 활성화 시 추천 arrays=30을 채우고 사용자 변경을 허용한다. `c2c=true` 또는 n_reprogram!=1은 422 unsupported_effect다. H1/H2는 추천 preset이다. 사용자가 tile_size와 adc_bits를 선택하며 여러 조합 비교는 같은 profile/checkpoint/seed를 갖는 요청들로 확장한다. capabilities는 검증된 tile_size/adc_bits 조합과 PPA preset 지원 여부를 제공한다. PPA preset은 측정 전압과 엔진 전압의 대응을 검증해야 하며 upstream SRAM 기본값을 그대로 CTFM으로 표시하지 않는다. 추가 ADC 구조·MUX·노드 선택은 검토 문서의 확장 제안이고 API 필드와 adapter 검증을 마친 뒤 공개한다.

job state는 queued/running/succeeded/failed/cancelled다. 실행 도중 stage는 parsing/calibrating/training/mapping/inference/ppa/exporting. cancel_requested는 상태와 별도 flag다. restart 시 orphan running은 failed(interrupted)로 표기하고 자동 성공/재실행하지 않는다. 취소는 worker subprocess와 해당 child들만 종료하고 원본·이전 결과는 보존한다.

작업 부분 성공은 child 결과에서 표현한다. 정확도 성공·PPA 실패이면 전체 experiment는 `partial`, job은 종료 성공과 `warnings`를 반환한다. 필수 정확도 실패 시 experiment/job failed다. `succeeded`와 전체 요청 효과 성공을 혼동하지 않도록 experiment.summary에 requested/completed/failed/skipped를 제공한다. 사용자가 요청한 엔진 unavailable은 enqueue 전 422로 거부한다.

## 결과 JSON 구조

최상위: schema_version, experiment_id, design_version, status, resolved_config, provenance, assumptions, warnings, runs[], artifacts[].

run: profile_ref, pool, mapping, effects, array_index, years, engine, status, reason, accuracy, loss_vs_digital_pp, loss_vs_mapped_pp, retention_loss_pp, mapping_metrics, adc_metrics, ppa. unavailable 측정·common 없음은 skipped, 외삽 비양수는 invalid. 집계 분모는 유효 run 수로 표시하며 실패를 정확도 0으로 포함하지 않는다.

artifact: id, kind, filename, media_type, sha256, size_bytes. 서버 관리 경로 대신 download URL을 제공한다. 설정 JSON, input/profile hash, split/checkpoint hash, 상태 CSV, 매핑 NPZ, 상세 metric CSV, summary JSON/MD, 그래프, 엔진 stdout을 실행별 불변 디렉터리에 저장한다. 폴더가 있으면 덮어쓰지 않는다.
