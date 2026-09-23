# C2C 계산 모듈 (core만, 미연결) — 2026-09-22

[완료 계획 P2](completion-plan-2026-09-21.md#p2-c2c-수동-가정-모드-권고-구현안)의 수동 가정 C2C 모델 중 **계산 모듈만** `packages/ctfm-core/src/ctfm/simulation/math.py`에 구현했다. API/schema/UI/worker 연결, `c2c=false` 제한 해제, `n_reprogram` 상한(1~100) 검증은 이번에 하지 않았다 — 다음 검토 후 별도 작업으로 진행한다. 상세 근거·검증 결과는 `local_report/03_REPORT_c2c-core.md`(소통 폴더)를 참고한다.

## 공개 함수

- `c2c_relative_cv_percent_to_ratio(cv_percent)`: 사용자가 입력하는 % 단위 relative CV를 아래 함수들이 쓰는 비율(ratio)로 바꾸는 **유일한** 변환 지점. 예: `5` (5%) → `0.05`.
- `c2c_factors(shape, cv, root_seed, profile_hash, array_index, reprogram_index, layer_name, polarity)`: `d2d_factors`와 동일한 lognormal 모델(c=cv, s=sqrt(log(1+c²)), f=exp(-s²/2+sZ))이지만 `array_index` 외에 `reprogram_index`(재기록/기록 단위)를 추가로 키에 포함한다. `adc_order`/`years`는 의도적으로 키에 없음 — 같은 식별자로 다시 호출하면 같은 ADC 순서/시간 비교에서도 항상 같은 표본을 재사용한다(호출자가 별도 캐시를 관리할 필요 없음, 순수 함수).
- `c2c_factor_statistics(factors)`: 생성된 배율 배열 자체의 표본 평균/표준편차/실효 CV(`empirical_cv`). **G_program이 아니라 factors에 대해서만 호출한다** — G_program의 산포는 각 weight의 서로 다른 nominal conductance를 포함하므로 주입 CV로 오인하면 안 된다(`local_report/03_REPORT_c2c-core.md`의 `test_c2c_factor_statistics_is_not_fooled_by_g_program_spread` 참고).
- `observed_range_violation(g_program, g_min_s, g_max_s)`: 프로그램된 conductance 중 관측 pool 범위를 벗어난 비율만 보고한다. **자동 clipping은 하지 않는다**(08 명세 3장).

## 사용 예시(향후 연결 시)

```python
from ctfm.simulation.math import c2c_factors, c2c_relative_cv_percent_to_ratio

cv = c2c_relative_cv_percent_to_ratio(5)  # 사용자 입력 "5%"
factors, info = c2c_factors(mapped['g_plus'].shape, cv, root_seed, profile_hash,
                            array_index, reprogram_index, layer_name, 'plus')
g_program = mapped['g_plus'] * d2d_factor * factors  # D2D와 동일하게 단순 곱셈, 별도 apply 함수 없음
```

## 설계 결정 근거

- **D2D와 코드 공유**: `d2d_factors`의 정규화·RNG·검증 로직을 `_mean_one_lognormal` 내부 헬퍼로 추출해 C2C와 공유했다. `d2d_factors`의 외부 동작(에러 메시지 포함)은 완전히 동일하게 유지된다 — 기존 `test_simulation_math.py`의 D2D 테스트가 무수정으로 통과함으로 확인.
- **RNG 키에 `reprogram_index` 추가**: D2D는 배열 생성 시 1회 고정이라 `array_index`까지만 필요하지만, C2C는 "재기록마다" 새로 뽑아야 하므로 `reprogram_index`를 D2D와 다른 위치의 추가 축으로 넣었다. `adc_order`/`years`를 넣지 않은 것은 지시서 요구사항 그대로다(같은 기록을 시간·ADC 순서 비교에 재사용).
- **shape 명시 검증**: D2D는 원래 shape를 검증하지 않지만(numpy에 위임), 이번 작업 지시서가 C2C에 대해 명시적으로 "잘못된 shape 거부"를 요구해 `_validate_c2c_shape`를 C2C 전용으로 추가했다. D2D 쪽 동작은 바꾸지 않았다.
- **G_program 조합에 별도 "apply" 함수를 만들지 않음**: 기존 D2D도 호출부에서 `g = mapped[key] * factor`로 단순 곱셈만 한다(`ctfm/simulation/__init__.py`). 같은 관례를 따라 C2C도 곱셈 자체는 감싸지 않았다 — 중복 소자 모델을 만들지 않기 위함.
