# frontend_v3 구현 정리

## 목표

- `frontend_v3`를 최종 프론트엔드 작업 공간으로 사용한다.
- `frontend_v2`는 기능/플로우 참고용 레퍼런스로 유지한다.
- 이번 문서는 UI 재설계와 화면별 구현 방향을 먼저 고정하는 목적이다.

## 작업 원칙

- 기존 글래스 UI와 과한 블러 효과는 제거한다.
- 전체 배경은 화이트를 기본으로 사용한다.
- 서비스 전반의 인상은 또렷하고 깨끗하게 유지한다.
- 시선 흐름은 단순하게 가져가고, 화면마다 동일한 텍스트 배치 규칙을 사용한다.
- `frontend_v2`의 비즈니스 로직은 필요한 부분만 선별 이식하고, UI는 `frontend_v3`에서 새로 구성한다.

## 디자인 방향

### 컬러

- Background: `#FFFFFF`
- Main Pink: `#FF5C93`
- Sub Pink: `#FFD6E5`
- Gray 900: `#222222`
- Gray 700: `#555555`
- Gray 500: `#8B8B95`
- Gray 200: `#E9E9EE`
- Gray 100: `#F6F6F8`

### 톤 앤 무드

- 선명한 흰 배경 위에 핑크를 포인트로 사용한다.
- 카드, 버튼, 말풍선은 반투명 대신 불투명에 가깝게 구성한다.
- 그림자도 퍼지는 느낌보다 얕고 선명한 느낌으로 제한한다.
- 일러스트나 상품 이미지는 흐림 없이 원본 선명도를 유지한다.

### 타이포그래피

- 기본 폰트는 `Pretendard`를 우선 사용한다.
- 메인 텍스트는 크고 짧게, 서브 텍스트는 간결하게 보조한다.
- 화면별 문장 길이가 길어져도 줄바꿈이 자연스럽게 보이도록 행간을 고정한다.

권장 텍스트 스케일:

- Display: `32 / 40`, `700`
- Title 1: `28 / 36`, `700`
- Title 2: `24 / 32`, `700`
- Body 1: `18 / 28`, `500`
- Body 2: `16 / 24`, `500`
- Caption: `13 / 18`, `500`

## 공통 UI 규칙

중요 원칙:

- 화면별로 직접 여백과 크기를 박아 넣지 않는다.
- 공통 레이아웃 값은 별도 파일에서 관리하고, 각 화면은 그 값을 참조만 한다.
- 추후 전체 여백, 버튼 높이, 텍스트 간격을 바꾸더라도 화면 파일을 하나씩 수정하지 않게 만든다.

### 화면 레이아웃

- 좌우 기본 패딩은 `24`
- 상단 Safe Area 아래 첫 요소 시작 간격은 `20`
- 제목과 설명 간격은 `8`
- 주요 섹션 간 간격은 `24`
- 카드 내부 패딩은 `20` 또는 `24`
- 하단 고정 버튼 영역은 `24` 패딩 + `56` 높이 기준

### 텍스트 배치

- 메인 텍스트는 화면 상단 1/3 지점 안쪽에서 시작한다.
- 서브 텍스트는 메인 텍스트 바로 아래 붙이고, 폭은 화면 너비를 넘기지 않게 제한한다.
- 긴 문장도 단어 단위 줄바꿈이 자연스럽게 되도록 `maxLines` 억지 제한을 최소화한다.
- 말풍선/카드 안 텍스트는 중앙 정렬보다 좌측 정렬을 기본으로 한다.

### 버튼 규칙

- 메인 CTA 버튼 높이: `56`
- 보조 버튼 높이: `48`
- 버튼 최소 너비: `200`
- 버튼 모서리 반경: `16`
- 기본 버튼 위치: 하단 고정 또는 콘텐츠 마지막 영역 바로 아래
- 동일 플로우 내 버튼 위치는 매 화면 동일하게 유지한다.

### 행간

- 큰 제목: `1.25`
- 본문: `1.5`
- 말풍선 내부 문장: `1.45`
- 버튼 텍스트: `1.2`

### 이미지 규칙

- 상품 이미지는 가능한 원본 비율을 유지한다.
- 흐림 처리, 블러 오버레이, 반투명 마스크는 사용하지 않는다.
- 로딩 중 이미지를 임시 배경색으로 감싸더라도 노출 시점에는 선명한 원본이 보이게 한다.

## 공통 레이아웃 제어 구조

목표:

- 레이아웃을 화면마다 따로 수정하지 않고, 공통 파일에서 제어한다.
- `frontend_v3`의 모든 화면은 같은 레이아웃 래퍼와 토큰을 사용한다.
- 추후 간격, 버튼 위치, 최대 폭, 헤더 높이를 한 번에 조정할 수 있게 한다.

핵심 방식:

- 숫자값 직접 입력 금지
- 공통 spacing/radius/height/token 파일 사용
- 모든 화면은 공통 `AppScaffold` 또는 `ScreenFrame` 위에서 렌더링
- 화면별 차이는 preset으로만 조정

### 추천 파일 구조

- `lib/app/theme/app_spacing.dart`
- `lib/app/theme/app_radii.dart`
- `lib/app/theme/app_sizes.dart`
- `lib/app/theme/app_text_styles.dart`
- `lib/app/theme/app_colors.dart`
- `lib/shared/layout/app_layout.dart`
- `lib/shared/layout/layout_presets.dart`
- `lib/shared/layout/screen_frame.dart`
- `lib/shared/layout/bottom_cta_layout.dart`
- `lib/shared/layout/content_constraints.dart`

### 파일 역할

`app_spacing.dart`

- 화면 좌우 패딩
- 섹션 간격
- 텍스트 간격
- 카드 내부 패딩

`app_radii.dart`

- 카드 반경
- 버튼 반경
- 말풍선 반경

`app_sizes.dart`

- 버튼 높이
- 헤더 높이
- 캐릭터 기본 크기
- 이미지 카드 기본 높이

`app_layout.dart`

- 현재 화면 크기 기준으로 사용할 실제 패딩/최대폭/하단 버튼 여백 계산
- 작은 기기와 큰 기기에서 레이아웃이 무너지지 않게 보정

`layout_presets.dart`

- 화면 유형별 레이아웃 preset 정의
- 예시: `standard`, `onboarding`, `conversation`, `loading`, `cartCompact`

`screen_frame.dart`

- 모든 화면이 공통으로 사용하는 레이아웃 래퍼
- Safe Area, 배경색, 상단/하단 패딩, 최대 폭, 스크롤 여부를 공통 처리

`bottom_cta_layout.dart`

- 하단 고정 버튼의 높이, 위치, 여백 통일
- 마지막 CTA가 화면마다 튀지 않게 제어

`content_constraints.dart`

- 텍스트 블록 최대 폭
- 카드 최대 폭
- 태블릿/가로모드 대응용 content width 제어

### 사용 규칙

- 화면 파일 안에서 `EdgeInsets.symmetric(horizontal: 24)` 같은 하드코딩을 하지 않는다.
- `SizedBox(height: 24)`도 직접 쓰지 않고 spacing token을 사용한다.
- 버튼 높이, 카드 반경, 말풍선 패딩은 공통 컴포넌트 내부에서만 관리한다.
- 화면은 `preset`만 선택하고, 세부 값은 공통 레이아웃 파일이 책임진다.

예시:

- 스플래시: `ScreenFrame(preset: LayoutPreset.standard)`
- 온보딩: `ScreenFrame(preset: LayoutPreset.onboarding)`
- 스몰토크: `ScreenFrame(preset: LayoutPreset.conversation)`
- 장바구니: `ScreenFrame(preset: LayoutPreset.cartCompact)`

### 기대 효과

- 전체 좌우 여백을 `24 -> 20`으로 바꿀 때 한 파일만 수정하면 된다.
- 버튼 높이를 `56 -> 52`로 바꿔도 전 화면에 반영된다.
- 텍스트 간격과 행간 규칙이 유지되어 화면별 들쭉날쭉함이 줄어든다.
- 작은 화면 대응을 공통 로직으로 처리할 수 있다.

## 공통 컴포넌트 가이드

`frontend_v3`에서 공통화할 우선 컴포넌트:

- `ScreenFrame`: 공통 레이아웃 래퍼
- `AppScaffold`: 흰 배경, 공통 Safe Area, 공통 패딩 처리
- `AppHeader`: 메인 텍스트 + 서브 텍스트 조합
- `PrimaryButton`: 높이/반경/폰트 규칙 통일
- `SecondaryButton`
- `SpeechBubble`: 딸랑구 말풍선 전용
- `ProgressDots`: 온보딩 및 단계 표시
- `PlatformBadge`
- `ProductImageCard`

## 화면 플로우 초안

PDF 기준 후보 플로우:

1. 스플래시
2. 온보딩
3. 본인확인/스몰토크
4. 사용 중인 플랫폼 불러오기
5. 구매 이력 불러오기
6. 메인 홈 화면
7. 메인 구매 진입 화면
8. 상품 추천/상품 확인
9. 수량 확인
10. 앱 내부 장바구니 담기 진행
11. 장바구니 확인
12. 배송지 확인
13. 비밀번호 입력
14. 실제 결제 자동화 오버레이
15. 최종 완료 화면
16. 홈 화면 복귀

메모:

- `UI_modplan.pdf` 기준으로 홈 화면은 선택이 아니라 명시적 설계 대상이다.
- 플랫폼 확인 화면과 구매 이력 화면의 정확한 순서는 PDF에도 `순서 확인 필요`로 남아 있으므로, 현재는 `스몰토크 이후` 가정으로 정리한다.
- 온보딩의 `"시작하기"`는 PDF 원문 기준 `메인 홈 화면`으로 이동하는 흐름이 우선이다.

## PDF 반영 메모

`UI_modplan.pdf`에서 추가로 확정된 사항:

- 스몰토크 화면은 동일 레이아웃에서 대사만 바뀌는 구조여야 한다.
- 대사 텍스트는 외부 주입값으로 처리하고, 특정 단어 강조색 처리를 지원해야 한다.
- 대사 전환 시 말풍선 텍스트는 페이드 전환이 들어가면 좋다.
- 홈 화면은 `장바구니 보기`, `지난 주문 내역`, `딸랑구야 도와줘!` CTA를 포함하는 독립 화면이다.
- 실제 결제 시점에는 풀스크린이 아니라 하단 배너형 `Accessibility Service` 오버레이 화면이 별도로 필요하다.
- 자동화 완료 후에는 별도의 최종 완료 화면이 필요하다.

PDF에서 아직 미정인 사항:

- 플랫폼 확인 / 구매 이력 확인의 정확한 위치
- 일부 `"대화 종료"` 버튼 스타일 지시가 페이지별로 다르게 적혀 있는 부분

현재 문서 반영 원칙:

- 화면 구조와 정보 구조는 PDF 기준으로 우선 반영
- 세부 스타일 충돌은 공통 디자인 시스템 단계에서 하나로 정리

## 자동화 시점 정리

핵심 구분:

- `장바구니 담기` 단계는 딸랑구 앱 내부 UI에서만 처리한다.
- `실제 자동화`는 사용자가 결제를 최종 확정한 뒤에만 시작한다.

### 1. 앱 내부 처리 구간

아래 단계는 실제 쇼핑앱을 아직 조작하지 않는다.

- 상품 추천/상품 확인
- 수량 확인
- 앱 내부 장바구니 담기 진행
- 장바구니 확인
- 배송지 확인
- 비밀번호 입력

이 구간의 의미:

- 사용자가 무엇을 살지 정하고
- 몇 개를 담을지 정하고
- 장바구니 요약을 확인하고
- 배송지와 비밀번호를 입력하는 과정
- 모두 `딸랑구 앱 내부 상태`로만 관리됨

### 2. 실제 외부 앱 자동화 시작 시점

실제 자동화는 아래 조건이 모두 끝난 뒤 시작한다.

- 사용자가 `결제할게요` 또는 동등한 최종 결제 의사를 확정
- 배송지 확인 완료
- 비밀번호 입력 완료

그 다음에 일어나는 일:

- 실제 쇼핑앱 자동화 시작
- 이때 풀스크린 딸랑구 UI 대신 `실제 결제 자동화 오버레이`가 등장
- 사용자는 실제 쇼핑앱 화면 위에 하단 배너형 UI를 보게 됨

### 3. 문서 용어 정리

- `앱 내부 장바구니 담기 진행 화면`
  - 우리 앱 안에서만 상태를 보여주는 진행 화면
  - 아직 실제 쇼핑앱 자동화는 아님

- `실제 결제 자동화 오버레이`
  - 외부 쇼핑앱 자동화가 실제로 시작된 뒤 나타나는 하단 배너형 UI
  - 결제 단계에서만 등장

## 화면 분류

핵심 관계:

- `새로 만들어야 하는 화면`은 UI 기준 분류다.
- `화면은 새로 만들되 로직은 가져올 화면`은 그 하위집합이다.
- 즉 모든 화면이 로직 재사용 대상은 아니고, 일부만 기존 로직을 옮겨 쓸 수 있다.

정리식:

- `새로 만들어야 하는 화면`
  = `UI는 새로 + 로직도 일부 재사용 가능`
  + `UI도 새로 + 로직도 새로 필요`

### 1. UI를 새로 만들어야 하는 화면 전체

아래 화면들은 `frontend_v3`에서 화면 UI를 새로 만든다.

1. 스플래시 화면
2. 온보딩 화면
3. 스몰토크 화면
4. 사용 중인 플랫폼 불러오기 화면
5. 구매 이력 불러오기 화면
6. 메인 구매 화면
7. 장바구니 화면
8. 메인 홈 화면
9. 실제 결제 자동화 오버레이
10. 최종 완료 화면

### 2. UI는 새로 만들고, 기존 로직을 가져올 수 있는 화면

위 목록 중 아래 화면들은 기존 코드에서 상태 흐름이나 서비스 로직을 재사용할 수 있다.

1. 스플래시 화면
- 기존 참고 파일: `frontend_v2/lib/features/shopping_v2/screens/shopping_splash_screen.dart`
- 가져올 것:
  - 자동 이동 타이밍
  - 로고/캐릭터 asset 연결 방식
- 새로 만들 것:
  - 전체 레이아웃
  - 텍스트 구성
  - 전환 방식

2. 스몰토크 화면
- 기존 참고 파일: `frontend_v2/lib/features/shopping_v2/screens/smalltalk_screen.dart`
- 가져올 것:
  - 질문 순서와 진행 흐름
  - `VoiceTurnService`
  - TTS/STT 연동 구조
- 새로 만들 것:
  - 말풍선 중심 UI
  - 캐릭터 배치
  - 질문/답변 표시 레이아웃

3. 사용 중인 플랫폼 불러오기 화면
- 기존 참고 파일: `frontend_v2/lib/features/shopping_v2/screens/platform_scan_screen.dart`
- 가져올 것:
  - mock 플랫폼 목록
  - reveal 타이밍
  - 완료 콜백 구조
- 새로 만들 것:
  - 플랫폼 배지 UI
  - 화면 배치
  - 애니메이션 방식

4. 구매 이력 불러오기 화면
- 기존 참고 파일: `frontend_v2/lib/features/shopping_v2/screens/purchase_history_loading_screen.dart`
- 가져올 것:
  - mock 구매 이력 데이터
  - 순차 노출 로직
  - 완료 콜백 구조
- 새로 만들 것:
  - 선명한 상품 이미지 카드
  - 텍스트 라벨 구조
  - 전체 배치

5. 메인 구매 화면
- 기존 참고 파일: `frontend_v2/lib/features/shopping_v2/screens/shopping_voice_screen.dart`
- 가져올 것:
  - `ShoppingFlowController`
  - 단계 enum / 상태 전이
  - API 호출 구조
  - 웹뷰 진입 조건
- 새로 만들 것:
  - 메인 레이아웃
  - 상품 카드 UI
  - 수량/주소/비밀번호 단계별 화면
  - 장바구니 요약 표현

### 3. UI도 새로 만들고 로직도 새로 필요한 화면

1. 온보딩 화면
- 기존 대응 화면이 없음
- `frontend_v3`에서 신규 생성

2. 장바구니 화면
- 기존에는 메인 구매 화면 내부 상태/카드로 섞여 있음
- 별도 화면으로 분리하려면 새 UI와 새 화면 구조가 필요
- 단, 데이터는 추후 메인 구매 플로우 상태를 참조할 수 있음

3. 메인 홈 화면
- 기존 `home_screen.dart`는 전화 호출 중심 UX
- PDF 기준 독립 홈 화면 요구가 명시되어 있음
- 새 IA와 새 레이아웃 기준으로 재설계

4. 실제 결제 자동화 오버레이
- 기존 대응 화면이 없음
- Flutter 쪽에서는 배너 UI, 축소/확장 전환, 콜백 지점만 정의

5. 최종 완료 화면
- 기존 대응 화면이 없음
- 자동화 완료 후 보여줄 정적 완료 화면으로 신규 생성

### 4. 거의 그대로 가져다 쓸 수 있는 예외 화면

1. 결제/쇼핑 WebView 화면
- 기존 파일: `frontend_v2/lib/presentation/screens/call/payment_webview_screen.dart`
- 역할:
  - 실제 쇼핑몰 웹페이지를 앱 안 WebView로 띄우는 기능 화면
  - 상품 페이지 열기, 장바구니 담기, 배송지 확인, 결제 준비 같은 작업 수행
- 그대로 가져갈 수 있는 이유:
  - 사용자 메인 브랜딩 화면이 아니라 기능 수행용 화면에 가깝다
  - WebView 제어, 자동화 상태 처리, 결과 콜백 로직이 이미 복잡하게 구현돼 있다
  - 디자인보다 기능 안정성이 더 중요하다
- 적용 원칙:
  - 1차에서는 엔진과 구조를 거의 그대로 재사용
  - 필요하면 상단 헤더/상태 텍스트만 `frontend_v3` 톤에 맞게 얇게 수정

2. UI Preview 화면
- 개발용 내부 화면
- 우선순위 낮음
- 필요하면 나중에 `frontend_v3` 기준으로 간단히 다시 만들면 됨

### 5. 이번 v3 범위에서 우선 제외할 기존 화면

1. 기존 auth 화면
- `login_screen.dart`
- `register_screen.dart`
- `presentation/screens/auth/splash_screen.dart`

2. 기존 call 기반 화면
- `call_screen.dart`

3. 기존 home 화면
- `home_screen.dart`

## 바로 실행 가능한 결론

- `frontend_v3`에서 새로 만들어야 하는 핵심 사용자 화면:
  - 스플래시
  - 온보딩
  - 스몰토크
  - 플랫폼 불러오기
  - 구매 이력 불러오기
  - 홈
  - 메인 구매
  - 장바구니
  - 실제 결제 자동화 오버레이
  - 최종 완료 화면

- 그중 기존 로직을 재사용할 화면:
  - 스플래시
  - 스몰토크
  - 플랫폼 불러오기
  - 구매 이력 불러오기
  - 메인 구매

- UI와 로직을 사실상 새로 잡아야 하는 화면:
  - 온보딩
  - 장바구니
  - 홈
  - 실제 결제 자동화 오버레이
  - 최종 완료 화면

- 거의 그대로 가져갈 수 있는 기능 화면:
  - `PaymentWebViewScreen`

## 화면별 1차 구성 분해

이 섹션은 실제 구현 단위로 화면을 쪼갠 것이다.

분해 기준:

- `screen`: 라우트 단위 화면 파일
- `section`: 화면 안의 큰 영역
- `widget`: 재사용 가능한 하위 UI 조각
- `logic source`: 기존에서 가져올 로직 출처

### 1. 스플래시 화면

screen:

- `features/shopping/screens/splash_screen.dart`

sections:

- 중앙 로고/캐릭터 영역
- 메인 카피 영역
- 서브 카피 영역

widgets:

- `SplashLogoBlock`
- `SplashMessageBlock`

logic source:

- 자동 이동 타이밍
- 다음 화면 라우팅 분기
- 참고: `frontend_v2/lib/features/shopping_v2/screens/shopping_splash_screen.dart`

완료 조건:

- 스피너 없이 2초 내외 후 다음 화면으로 자연스럽게 이동

### 2. 온보딩 화면

screen:

- `features/onboarding/screens/onboarding_screen.dart`

sections:

- 상단 캐릭터/일러스트 영역
- 중앙 텍스트 영역
- 하단 페이지 인디케이터 영역
- 마지막 페이지 전용 CTA 영역

widgets:

- `OnboardingPageView`
- `OnboardingPageCard`
- `OnboardingCharacterBlock`
- `OnboardingIndicator`
- `OnboardingStartButton`

logic source:

- 신규 작성

완료 조건:

- 3페이지 스와이프 가능
- 마지막 페이지에서만 `"시작하기"` 노출
- 탭 시 다음 플로우로 이동

### 3. 스몰토크 화면

screen:

- `features/shopping/screens/smalltalk_screen.dart`

sections:

- 상단 진행 표시 영역
- 캐릭터 영역
- 딸랑구 말풍선 영역
- 사용자 마지막 답변 영역
- 음성 입력 버튼 영역

widgets:

- `SmallTalkProgress`
- `SmallTalkCharacter`
- `SpeechBubble`
- `HighlightedSpeechText`
- `UserReplyChip` 또는 `UserReplyBubble`
- `VoiceActionButton`

logic source:

- 질문 순서
- TTS/STT 상태 전이
- 음성 입력 시작/종료 흐름
- 대사 텍스트 외부 주입 구조
- 강조 단어 span 처리
- 참고: `frontend_v2/lib/features/shopping_v2/screens/smalltalk_screen.dart`
- 참고 service: `VoiceTurnService`

완료 조건:

- 질문이 순서대로 진행되고, 마지막 완료 상태가 자연스럽게 표현됨

### 4. 사용 중인 플랫폼 불러오기 화면

screen:

- `features/shopping/screens/platform_loading_screen.dart`

sections:

- 배경 스크린샷 영역
- 하단 배너 영역
- 배너 내부 상태 텍스트 영역
- 배너 내부 종료 액션 영역

widgets:

- `PlatformLoadingBackground`
- `PlatformLoadingBanner`
- `PlatformBadgeRow` 또는 `PlatformBadgeCluster`
- `PlatformBadge`
- `CloseConversationButton`

logic source:

- 플랫폼 mock 목록
- 순차 reveal 타이밍
- 완료 콜백
- 참고: `frontend_v2/lib/features/shopping_v2/screens/platform_scan_screen.dart`

완료 조건:

- 하단 배너가 슬라이드 업으로 등장하고, 사용자 이름을 포함한 상태 문구가 자연스럽게 노출됨

### 5. 구매 이력 불러오기 화면

screen:

- `features/shopping/screens/purchase_history_loading_screen.dart`

sections:

- 상단 설명 텍스트 영역
- 중앙 구매 이력 썸네일 영역
- 하단 진행 카운트 영역

widgets:

- `PurchaseHistoryHeader`
- `PurchaseHistoryThumbnailBoard`
- `PurchaseHistoryThumbnailCard`
- `LoadingCountText`

logic source:

- 구매 이력 mock 데이터
- 순차 노출 로직
- 완료 콜백
- 참고: `frontend_v2/lib/features/shopping_v2/screens/purchase_history_loading_screen.dart`

완료 조건:

- 상품 이미지가 선명하게 보이고, 진행 수치가 명확하게 보임

### 6. 메인 구매 화면

screen:

- `features/shopping/screens/shopping_screen.dart`

sections:

- 상단 진행 단계 영역
- 메인 응답 텍스트 영역
- 메인 콘텐츠 영역
- 하단 액션 영역

메인 콘텐츠 하위 상태:

- 메인 프로세스 진입 상태
- 상품 추천 상태
- 수량 선택 상태
- 앱 내부 장바구니 작업 상태
- 장바구니 확인 상태
- 주소 확인 상태
- 비밀번호 입력 상태
- 실제 결제 자동화 진입 직전 상태

widgets:

- `ShoppingProgressHeader`
- `AssistantResponseBlock`
- `ExampleReplyChips`
- `ProductSummaryCard`
- `QuantitySelectorCard`
- `CartStatusCard`
- `AddressConfirmCard`
- `PasswordPinPad`
- `CheckoutSummaryCard`
- `VoiceActionButton`
- `PrimaryBottomCta`

logic source:

- `ShoppingFlowController`
- 단계 enum / 상태 전이
- API 호출 구조
- 웹뷰 진입 조건
- 참고: `frontend_v2/lib/features/shopping_v2/screens/shopping_voice_screen.dart`

완료 조건:

- 각 상태가 한 화면 구조 안에서 안정적으로 전환되고, 텍스트 잘림이나 요소 겹침이 없음

### 7. 장바구니 화면

screen:

- `features/shopping/screens/cart_screen.dart`

sections:

- 상단 제목/설명 영역
- 장바구니 상품 요약 영역
- 가격 요약 영역
- 배송 정보 영역
- 결제 CTA 영역

widgets:

- `CartHeader`
- `CartItemSummaryCard`
- `CartPriceSummary`
- `DeliveryAddressBlock`
- `CheckoutButton`

logic source:

- 1차는 신규 화면으로 작성
- 추후 메인 구매 플로우 상태나 controller 데이터 참조 가능

완료 조건:

- 스크롤 없이 핵심 정보가 1화면에 들어옴

### 8. 메인 홈 화면

screen:

- `features/home/screens/home_screen.dart`

sections:

- 상단 홈 아이콘 영역
- 말풍선 인사 영역
- 캐릭터 영역
- 바로가기 카드 영역
- 하단 메인 CTA 영역

widgets:

- `HomeWelcomeHeader`
- `HomeIconBadge`
- `HomeSpeechBubble`
- `ShortcutCard`
- `StartShoppingButton`
- `QuickEntryCard`

logic source:

- 신규 작성

완료 조건:

- `딸랑구야 도와줘!` CTA가 실제 다음 메인 구매 플로우로 연결됨

### 9. 실제 결제 자동화 오버레이

screen:

- `features/shopping/screens/automation_overlay_screen.dart`

sections:

- 실제 쇼핑앱 배경 영역
- 하단 오버레이 배너 영역
- 진행 상태 텍스트 영역
- 종료 액션 영역

widgets:

- `AutomationOverlayBanner`
- `AutomationStatusText`
- `CloseConversationButton`

logic source:

- 신규 작성
- `onCancelPressed`
- `onAutomationComplete`

완료 조건:

- 비밀번호 입력 이후 실제 외부 앱 자동화가 시작될 때 배너 형태로 축소 전환되는 UI를 표현할 수 있음

### 10. 최종 완료 화면

screen:

- `features/shopping/screens/completion_screen.dart`

sections:

- 상단 완료 스테퍼 영역
- 완료 메시지 영역
- 체크 아이콘 영역
- 홈 복귀 CTA 영역

widgets:

- `CompletedProgressHeader`
- `CompletionMessageBlock`
- `CompletionBadge`
- `GoHomeButton`

logic source:

- 신규 작성

완료 조건:

- 자동화 완료 후 정적인 성공 화면으로 자연스럽게 사용 가능

### 11. 그대로 재사용할 기능 화면: Payment WebView

screen:

- `presentation/screens/call/payment_webview_screen.dart`

sections:

- 상단 상태 텍스트 영역
- WebView 본문 영역
- 자동화 진행 상태 영역

widgets:

- 기존 구조 최대한 재사용

logic source:

- WebView controller
- Kurly 자동화 흐름
- 결과 콜백
- 참고: `frontend_v2/lib/presentation/screens/call/payment_webview_screen.dart`

완료 조건:

- v3 메인 쇼핑 화면에서 문제 없이 진입/복귀 가능

## 구현 파일 초안

1차 파일 생성 후보:

- `frontend_v3/lib/features/onboarding/screens/onboarding_screen.dart`
- `frontend_v3/lib/features/onboarding/widgets/onboarding_page_card.dart`
- `frontend_v3/lib/features/onboarding/widgets/onboarding_indicator.dart`
- `frontend_v3/lib/features/shopping/screens/splash_screen.dart`
- `frontend_v3/lib/features/shopping/screens/smalltalk_screen.dart`
- `frontend_v3/lib/features/shopping/screens/platform_loading_screen.dart`
- `frontend_v3/lib/features/shopping/screens/purchase_history_loading_screen.dart`
- `frontend_v3/lib/features/shopping/screens/shopping_screen.dart`
- `frontend_v3/lib/features/shopping/screens/cart_screen.dart`
- `frontend_v3/lib/features/home/screens/home_screen.dart`
- `frontend_v3/lib/features/shopping/screens/automation_overlay_screen.dart`
- `frontend_v3/lib/features/shopping/screens/completion_screen.dart`
- `frontend_v3/lib/features/shopping/widgets/splash_logo_block.dart`
- `frontend_v3/lib/features/shopping/widgets/smalltalk_character.dart`
- `frontend_v3/lib/features/shopping/widgets/platform_badge.dart`
- `frontend_v3/lib/features/shopping/widgets/purchase_history_thumbnail_card.dart`
- `frontend_v3/lib/features/shopping/widgets/assistant_response_block.dart`
- `frontend_v3/lib/features/shopping/widgets/highlighted_speech_text.dart`
- `frontend_v3/lib/features/shopping/widgets/product_summary_card.dart`
- `frontend_v3/lib/features/shopping/widgets/quantity_selector_card.dart`
- `frontend_v3/lib/features/shopping/widgets/cart_price_summary.dart`

## 화면별 수정 정리

### 1. 스플래시 화면

목표:

- 스피너를 제거하고 정적인 인상으로 시작한다.
- 2초 내외 자동 전환은 유지 가능하지만, 시각적으로는 차분하고 즉시 이해되는 화면으로 만든다.

구현 방향:

- 화이트 배경
- 딸랑구 로고/캐릭터 중앙 배치
- 메인 문구 1줄, 서브 문구 1줄
- 로딩 스피너 제거
- 필요하면 하단에 작은 진행 바 대신 자연스러운 페이드 전환만 사용

### 2. 스몰토크 화면

목표:

- 딸랑구가 실제로 말하듯 보이게 만든다.
- 텍스트 카드보다 말풍선 중심 경험으로 바꾼다.

구현 방향:

- 캐릭터 근처 또는 상단 본문 영역에 `SpeechBubble` 적용
- 딸랑구 질문은 둥근 말풍선 안에 노출
- 사용자의 마지막 답변은 색이 약간 다른 보조 말풍선 또는 답변 태그로 표시
- 과한 애니메이션 대신 말풍선 등장 페이드/슬라이드 정도만 사용
- 좌측 정렬 기준으로 읽기 편하게 구성

### 3. 사용 중인 플랫폼 불러오는 화면

목표:

- 현재 무엇을 찾고 있는지 한눈에 이해되게 만든다.

구현 방향:

- 상단에 메인 텍스트: "사용하시는 쇼핑 플랫폼을 모으고 있어요"
- 중앙에는 플랫폼 로고 배지를 단순하고 선명하게 배치
- 레이더/유리 효과 대신 깔끔한 배지 등장 애니메이션 사용
- 발견된 플랫폼은 선명한 컬러, 미발견 플랫폼은 회색 톤 placeholder로 구분

### 4. 구매 이력 불러오는 화면

목표:

- 상품 이미지가 흐릿하지 않고 또렷하게 보이게 한다.

구현 방향:

- 제품 썸네일은 선명한 이미지 카드로 노출
- 텍스트 오버레이를 최소화하고, 필요하면 카드 하단 별도 라벨 영역 사용
- 상품 버블 형태를 유지하더라도 blur/filter 없이 구성
- 이미지 크롭 기준을 통일해 지저분해 보이지 않게 한다

### 5. 메인 구매 화면

목표:

- 텍스트가 끊겨 보이지 않게 하고, 주요 정보가 안정적으로 읽히게 만든다.

구현 방향:

- 상단 응답 영역 높이를 고정하지 말고 상황별 최소/최대 높이만 둔다.
- 긴 응답은 자연 줄바꿈 + 필요 시 내부 스크롤로 처리한다.
- 상품 카드, 수량 선택, 주소 확인, 비밀번호 입력 등 상태별 레이아웃을 분리한다.
- 현재 단계 텍스트와 행동 버튼이 서로 겹치지 않게 수직 구조를 단순화한다.

### 6. 장바구니 화면

목표:

- 스크롤 없이 한 화면에 핵심 정보가 보이게 한다.

구현 방향:

- 상품 수를 1~2개 대표 기준으로 요약해서 보여준다.
- 이미지, 상품명, 수량, 가격, 총액, 배송지, 결제 버튼 순으로 압축 배치
- 불필요한 설명 문구를 줄이고, 한 화면 요약형 카드로 정리
- 기기 높이가 작은 경우를 대비해 텍스트 길이와 카드 높이 상한을 먼저 설계한다

## 추가 화면: 온보딩

### 목적

- 첫 진입 사용자가 서비스 방식을 빠르게 이해하도록 돕는다.
- 텍스트 위주로 짧고 직관적으로 설명한다.

### 위치

- 스플래시 다음에 등장
- 기본 플로우: `스플래시 -> 온보딩 -> 홈`

### 노출 정책

- 기본 정책은 `최초 1회만 노출`로 가정한다.
- 개발 중 빠른 확인을 위해 추후 dev flag 또는 로컬 설정으로 `항상 노출` 모드를 둘 수 있다.

### 구성

- 총 3페이지
- 좌우 스와이프로 이동
- 하단 페이지 인디케이터 표시
- 현재 페이지 도트는 더 진하고 더 길게 표시
- 3페이지에서만 `"시작하기"` 버튼 노출
- 1, 2페이지에는 버튼 없음

### 페이지별 카피

1페이지

- 메인 텍스트: `전화하듯 말만 하면 돼요`
- 보조 요소: 말풍선 `딸기 사줘`

2페이지

- 메인 텍스트: `복잡한 결제도 걱정 마세요`
- 보조 요소: `주문 완료`, `결제 승인`

3페이지

- 메인 텍스트: `이제 딸랑구와 함께 편하게 쇼핑해보세요`

### 이미지/캐릭터

- 기존 캐릭터 자산 우선 사용
- 사용 후보:
  - `frontend_v2/assets/images/ddalangoo_calling.png`
  - `frontend_v2/assets/images/ddalangoo_cheerful.png`
  - `frontend_v2/assets/images/ddalangoo_happy.png`
  - `frontend_v2/assets/images/ddalangoo_curious.png`
  - `frontend_v2/assets/images/ddalangoo_top.png`
- 로고 텍스트 자산:
  - `frontend_v2/assets/images/ddalangoo_logo_text.png`
- 페이지별 배경 일러스트는 1차 구현에서 생략 가능
- 텍스트 + 캐릭터 중심으로 먼저 구현한다

### 인터랙션

- 스와이프는 기본 `PageView`
- 인디케이터 전환은 짧은 애니메이션 적용
- `"시작하기"` 버튼은 마지막 페이지에서만 하단 고정
- `"시작하기"` 탭 시 `메인 홈 화면`으로 이동

## frontend_v3 폴더 구조 제안

```text
frontend_v3/
  lib/
    app/
      app.dart
      routes.dart
      theme/
        app_colors.dart
        app_radii.dart
        app_sizes.dart
        app_text_styles.dart
        app_spacing.dart
        app_theme.dart
    core/
      network/
      services/
      storage/
    features/
      onboarding/
        screens/
        widgets/
      shopping/
        screens/
        widgets/
        controllers/
        models/
        services/
    shared/
      layout/
        app_layout.dart
        layout_presets.dart
        screen_frame.dart
        bottom_cta_layout.dart
        content_constraints.dart
      widgets/
        app_scaffold.dart
        app_header.dart
        primary_button.dart
        speech_bubble.dart
        progress_dots.dart
  assets/
    images/
```

## 이식 우선순위

`frontend_v2`에서 먼저 가져올 것:

- API client 구조
- 음성 관련 service
- 쇼핑 플로우 controller
- 기존 asset 이미지

`frontend_v2`에서 버리고 새로 만들 것:

- 글래스 관련 위젯
- blur 기반 배경
- 화면별 복잡한 겹침 레이아웃
- 상단 텍스트 고정 높이 중심 레이아웃

## 구현 우선순위

1. `frontend_v3` Flutter 기본 앱 초기화
2. 공통 테마/컬러/타이포 토큰 정리
3. 공통 레이아웃 토큰 및 `ScreenFrame` 제작
4. 공통 컴포넌트 제작
5. 스플래시 화면
6. 온보딩 3페이지
7. 스몰토크 화면
8. 플랫폼 불러오기 화면
9. 구매 이력 불러오기 화면
10. 메인 구매 화면
11. 장바구니 화면
12. `frontend_v2` 서비스/로직 이식

## 열린 메모

- 홈 화면에서 바로 메인 구매 플로우로 들어갈지, 한 번 더 스몰토크를 거칠지는 라우팅 정책으로 분리 가능
- 장바구니 화면은 실제 데이터 밀도에 따라 1화면 요약 레이아웃 시안이 한 번 더 필요할 수 있음
- 구매 이력 화면은 실제 API 응답 이미지 규격을 확인한 뒤 썸네일 비율을 최종 확정하는 것이 좋음
