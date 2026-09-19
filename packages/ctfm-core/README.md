# 공통 측정·시뮬레이션 연산

HTTP·DB·React에 의존하지 않는 `ctfm` Python 패키지입니다. 엔진 없는 측정 분석에서 PyTorch를 import하지 않습니다.

- `ctfm.measurement`: CSV/XLSX 원본 좌표 보존, pulse/IV/D2D/Retention 분석
- `ctfm.profiles`: 명시적 상태 채택, 네 풀, canonical CSV/hash, 검토 발행·새 revision 검증
- `ctfm.simulation`: 실측 후보 매핑, 고정 배열 D2D, Program ratio Retention, 타일별 ADC, 실제 MNIST 학습·추론
- `ctfm.adapters`: PyTorch, 설치 후 실제 ideal parity probe를 통과한 AIHWKit, 비활성 NeuroSim 상태

`parse_table(data,filename,sheet)`는 원본 행/열만 파싱합니다.
`analyze(kind,datasets,settings)`는 열/단위/물리 소자/조건/분기를 명시적으로 요구하고 확장한 설정·출처·제외 사유·원시/계산 테이블을 반환합니다.
같은 파일의 여러 branch/열 구간을 구분하는 `selection_key`로 다중 교차 구간을 지정할 수 있습니다.

`build_profile`, `publish_profile`, `revise_profile`, `validate_profile`, `states_csv`, `parse_states_csv`, `compute_profile_hash`가 API와 공유하는 프로필 경계입니다.

`run_experiment(config,profiles,output_dir,cache_dir=...,checkpoint_path=...,split_seed=...)`는 요청·실행 설정, 데이터/프로필/분할/체크포인트 hash, D0/M0/효과 결과와 signed loss를 저장합니다. 서비스는 최신07 명세에 따라 `split_seed=config["seed"]`를 전달합니다.

MNIST MLP 784→128→10, 공식60,000개에서55,000/5,000 분할, 테스트10,000개, Adam0.001·batch256·5epoch 마지막 checkpoint를 사용합니다. 후보 선택·ADC 범위는 validation만 사용합니다. 실행은 CPU float32이며 정확도 기준값을 조작하거나 외삽 정확도 감소를 강제하지 않습니다.

D2D null과0을 구분하고 observed G 범위로 clipping하지 않습니다. Retention 비양수 외삽은 invalid/null이며 집계 분모에서 제외합니다. C2C/PPA는 v1.1에서 비활성입니다. AIHWKit 미설치·실패는 해당 엔진 unavailable로 표시하고 PyTorch로 대체하지 않습니다.

```sh
uv run --locked pytest packages/ctfm-core/tests -q
```

Git fixture는 합성입니다. 원본 A1 파일의1024→1022·115µS 회귀는 원본 확보 후 별도 검증해야 합니다.
