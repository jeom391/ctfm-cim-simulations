> 상태 변경 (2026-09-18): 이 문서는 과거 계획·검토 또는 기술 참고 자료입니다. 구현 기준은 [확정 설계 v1.0.0](spec/README.md)입니다. 본문의 미확정·승인 대기·이전 규칙은 새 명세를 대체하지 않습니다.

# AIHWKit 유한 상태 + 비이상성 구현 가능성 조사

조사일: 2026-09-08. 공식 AIHWKit 1.1.0 문서·소스 기준.
**조사·설계 제안이며 미구현이다. 확정 명세나 현재 구현 상태를 의미하지 않는다.**

## 확인한 지원 범위

| 기능 | 공식 지원과 주의점 |
|---|---|
| 등간격 가중치 양자화 | `WeightModifierType.DISCRETIZE`, `DISCRETIZE_ADD_NORMAL`과 `res`가 있다. 부호 있는 가중치 공간의 등간격 이산화이지 임의 간격의 실측 소자 전도도 목록 입력 기능은 아니다. |
| 평가 시 modifier | `enable_during_test` 기본값은 false이며, true는 마지막으로 수정된 가중치를 평가에 사용하는 옵션이다. 설정만 넣고 순수 추론에서도 자동 적용됐다고 가정하면 안 된다. 실제 양자화 경로와 eval 결과를 검증해야 한다. |

위 두 항목: [공식 WeightModifierParameter](https://aihwkit.readthedocs.io/en/latest/api/aihwkit.simulator.parameters.inference.html).

`SinglePairConductanceConverter`는 가중치를 두 전도도 텐서로 변환하고 차이/스케일로 복원한다. `CustomPairConductanceConverter`는 `g_lst` 사이를 **선형 보간**한다. 따라서 목록에 없는 중간 전도도도 출력한다. 기본 가역성 검사도 있으므로 이를 실측 유한 상태 양자화기라고 소개하면 부정확하다. [공식 converter 소스](https://aihwkit.readthedocs.io/en/latest/_modules/aihwkit/inference/converter/conductance.html)

## 이번 프로젝트에 제안하는 연결

**가중치 → 각 G+/G−의 기록 목표를 실측 상태 목록에서 선택 → D2D·C2C 적용 → 읽기 변동을 반영한 추론.**

- 결정적인 상태 선택은 `BaseConductanceConverter` 확장 또는 별도 매핑 단계로 작성할 수 있다. 변환기는 반복 가능한 결정적 변환을 요구하므로 무작위 편차 생성과 분리한다. [공식 BaseConductanceConverter](https://aihwkit.readthedocs.io/en/latest/_modules/aihwkit/inference/converter/base.html)
- 전도도 단위 programming noise를 넣고 가중치로 복원하는 연결은 `BaseNoiseModel`에 존재한다. 실측 CTFM 모델은 별도 구현해야 하며 기존 PCM 모델의 계수를 그대로 사용하지 않는다. 기본 drift 경로는 가중치를 다시 전도도로 변환하므로, 비가역적인 유한 상태 양자화기와 무검토 조합하면 이미 흔들린 값을 재양자화할 수 있다. 이번 무열화 추론에서는 기록된 전도도 상태를 명시적으로 유지하는 설계가 안전하다. [공식 BaseNoiseModel 소스](https://aihwkit.readthedocs.io/en/latest/_modules/aihwkit/inference/noise/base.html)

아래는 **프로젝트용 간략 모델 제안**이다.

1. 가상 배열마다 물리 소자별 D2D 오차를 한 번 뽑고 해당 배열의 재기록 동안 유지한다.
2. 매 재기록에서는 같은 목표 상태에 C2C 오차를 새로 뽑는다. 그 기록값은 테스트 전체에서 유지한다.
3. 읽기 변동은 저장값을 바꾸지 않고 읽는 시점에 반영한다. 전도도 쌍 단위 오차를 툴의 가중치 단위 오차로 바꿀 때 스케일과 두 소자 오차를 고려해야 한다.
4. **유한한 것은 목표 상태 목록이다. 실제 기록·읽기 값은 목표 주변에서 흔들린다. 오차 적용 후 목록에 다시 반올림하면 편차가 소실되므로 하지 않는다.**

현재처럼 D2D·C2C·읽기 표준편차를 종류별 숫자 하나로 받는 근사도 유한 상태와 함께 적용 가능하다. 단, 독립·가우시안·상태 비의존 가정이며 정확한 물리 모델을 보증하지 않는다. 상태별 표준편차는 정밀 확장 후보로 남기고 입력 확정을 별도 협의한다. 편차를 합칠 때 중복 추정하지 않아야 한다. 잡음 이후 경계 처리도 실측 범위/목표 범위를 구별해 검증할 사항이다.

## 최소 데이터 의미

유한 상태 재현에는 **기록 가능한 상태별 대표 G 목록**이 필요하다. 상태 수만 주면 등간격 가정까지만 가능하다. Gmin/Gmax는 이 사용할 목록의 최저·최고 대표값이며, 임의 I–V 스윕의 극값이나 문턱전압 차이를 뜻하지 않도록 측정 요구에서 정의해야 한다. 이는 현재 전도도 기반 매핑을 위한 프로젝트 정의다. 동일 읽기 조건의 상태별 출력과 선택 편차를 함께 확보하는 것을 제안한다.
