# 통합 웹 프론트엔드

React + TypeScript 단일 앱을 구현할 위치입니다. 현재는 디렉터리 골격이며 실행 가능한 앱은 아직 없습니다.

| URL | 페이지 | 소스 |
|---|---|---|
| / | 홈, 기능 선택 | src/pages/home/ |
| /measurements | 측정 분석과 프로필 검토·발행 | src/pages/measurements/ |
| /simulator | 실험 설정·진행·결과 비교 | src/pages/simulator/ |

src/components는 공통 UI, src/lib/api는 API 호출 계층입니다. 분석/시뮬레이션 계산은 서버 책임이며 프론트에서 중복 구현하지 않습니다. 시뮬레이터 내부 모델·ADC·Retention 비교는 같은 페이지의 탭/설정으로 제공하며 별도 앱으로 분리하지 않습니다.

구현 기준: [화면/API](../../docs/spec/04-web-api.md), [프로필](../../docs/spec/02-device-profile.md). API 타입의 원본은 packages/contracts이며 실제 타입 생성은 P0에서 수행합니다.
