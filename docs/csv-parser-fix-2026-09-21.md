# CSV 파서·측정 분석 수정 (2026-09-21)

## 완료 범위

최신 공유 원본 `data/reference/ltp-ltd-2026-09-21`의 CSV 10개를 대상으로 수정했다. 기존 main a4b3ef2에서 이어지는 `codex/fix-measurement-csv` 브랜치의 작업이다.

- 기존 파서는 Remarks 설명행을 헤더로 오인하거나 뒤쪽 장비 보조표를 측정 행으로 읽었다.
- Time / MeasResult1_value / MeasResult2_value 헤더로 알려진 장비 출력 형식을 식별한다. 제목·Device ID·Remarks와 빈 줄 뒤의 알려진 장비 보조표를 분리하고 제외 범위를 warnings로 반환한다.
- 원본 파일 해시와 1부터 시작하는 원본 행 번호를 보존한다. 열의 물리량·단위는 계속 명시적으로 매핑해야 한다.
- 중간 공백 이후 다시 나타나는 측정값, 복수 측정 헤더, 미확인 보조표는 오류로 처리한다. 잘못된 측정 숫자는 삭제하지 않고 분석 단계에서 행 번호와 함께 오류를 낸다.
- 일반 CSV/XLSX 경로와 분석 공식은 유지한다. 모든 임의 장비 형식을 자동 인식한다는 의미는 아니다.

## 변하지 않은 추출 기준

6초 이후, 다음 쓰기 시작 행 j의 j-2행에서 읽기 전류를 채택한다. 초기 전류를 차감하지 않고 G = ID / 0.1 V로 환산한다. 마지막 읽기 구간처럼 다음 전환이 없는 구간은 제외한다. 추출 규칙과 상태 식별 체계가 같아 parser_version은 1.0.0을 유지하며, 장비 표 인식 규칙 v1은 warnings에 기록한다.

## 검증

- 실제 CSV 10개 모두 12,000개 측정 행을 읽고 파일별 510개 후보를 추출했다. SHA256·원본 행 범위·첫/마지막 전류/전도도를 manifest와 대조했다.
- A1~A5 각각 LTP/LTD 후보 1,020개로 프로필 생성·발행 함수를 검증했다. 이는 테스트 메모리 안의 검증이며 운영 DB에 프로필을 발행한 것은 아니다.
- 구판 A1의 11.5 uA를 강제하던 선택적 회귀 테스트를 실제 해당 원본 행의 전류와 비교하도록 수정했다.
- 관련 테스트 결과: **57 passed, 2 skipped, 6 subtests passed**. skip 2개는 선택적 A1 테스트의 미지정 개수와 구판 고정 1024행 검사다. 최신 10개 파일의 개수·행 검증은 별도 테스트에서 모두 통과했다.
- 웹 브라우저 업로드부터 화면 표시까지의 종단 검증 및 다른 실측 IV/Retention 파일 검증은 이번 결과에 포함되지 않는다. 기존 측정 분석 테스트는 함께 실행했다.

재실행 (저장소 루트, 프로젝트 Python 환경):

```powershell
$env:PYTHONPATH="$PWD/packages/ctfm-core/src"
python -m pytest -q packages/ctfm-core/tests/test_latest_pulse_csv.py packages/ctfm-core/tests/test_measurement_profiles.py packages/ctfm-core/tests/test_measurement_review.py packages/ctfm-core/tests/test_input_limits.py
```

위 기본 명령은 선택적 A1 환경변수 테스트를 제외한 54개 테스트와 6개 하위 테스트를 실행한다. 추가 A1 테스트는 CTFM_A1_FILE, CTFM_A1_DIRECTIONS=ltd, CTFM_A1_COLUMNS를 해당 파일에 맞게 지정한다.

## 다음 작업

개발 담당은 이 브랜치를 검토·통합한 뒤 측정 페이지에서 같은 CSV를 업로드하고 명시적 열 매핑으로 분석 결과를 확인한다. C2C 수동 입력, NeuroSim 실행 연동, 정확도 모델과 NeuroSim 입력 일치는 별도 후속 작업이며 이번에 변경하지 않았다.
