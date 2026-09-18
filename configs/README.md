# 설정

단일 실행 파이프라인에서 사용하는 버전 관리 설정입니다.

- experiments/: MNIST, 풀/매핑, 효과, seed 등 실험 preset
- hardware/: 모든 가정값과 엔진 commit을 명시한 NeuroSim 하드웨어 preset

현재 하위 폴더는 scaffold입니다. 루트의 로컬 mnist-observed.json은 미커밋 참조 구현 설정이며 검증 후 experiments로 이관합니다. 실측값이나 개인 경로를 공개 preset에 넣지 않습니다. 실행 시 기본값을 모두 확장한 resolved config와 hash를 artifact에 저장합니다.
