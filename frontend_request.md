# FrontEnd -> BackEnd/AI 요청사항

# Backend Handoff: Speech Segment 분리 + 프론트 순차 재생

작성일: 2026-08-06

## 목적

딸랑구 음성이 재생될 때, 말풍선 텍스트도 전체 문장을 한 번에 보여주지 않고 "한 문장씩" 순차적으로 표시하고 싶다.

이 기능은 프론트 단독 처리보다, 백엔드가 문장 단위를 명시적으로 내려주고 프론트가 그 순서를 따라 재생/표시하는 구조가 더 적합하다.

이 문서는 실제 구현 요청이 아니라, 백엔드 전달용 TODO 및 권장 구현 방향 정리 문서다.

## 현재 상태

### 프론트 현재 동작

- `frontend_v3/lib/features/shopping/screens/shopping_flow_screen.dart`
  - 말풍선은 현재 `assistantMessage` 전체 문자열을 그대로 표시한다.
  - 음성도 현재 `VoiceService.speak(text)`로 전체 문자열을 한 번에 TTS 요청한다.
- `frontend_v3/lib/core/services/voice_service.dart`
  - `/api/voice/tts`에 `{"text": "...전체 문장..."}` 형태로 요청한다.

### 백엔드 현재 동작

- `backend/app/schemas/agent.py`
  - `AgentResponse`에는 현재 `assistantMessage`만 있고 `speechMode`, `speechSegments`가 없다.
- `backend/app/routers/voice.py`
  - `/api/voice/tts`는 단일 텍스트를 단일 오디오로 변환한다.

### 참고

- 프론트의 `AgentResponse` 파싱 모델에는 이미 `speechMode`, `speechSegments` 필드가 준비되어 있다.
  - `frontend_v3/lib/data/models/agent_model.dart`
- 즉, 프론트 모델은 일부 준비되어 있지만, 백엔드 응답 계약은 아직 연결되지 않은 상태다.

## 왜 백엔드에서 분리하는 게 맞는가

프론트에서 단순히 문자열을 문장 부호 기준으로 잘라도 동작은 가능하다. 하지만 아래 이유로 백엔드가 분리 기준을 내려주는 쪽이 더 안정적이다.

- 한국어 문장 경계가 항상 단순하지 않다.
- 상품명, 옵션, 수량, 주소, 전화번호 같은 텍스트는 프론트 임의 분리 시 어색하게 끊길 수 있다.
- 나중에 TTS 발화 단위와 화면 표시 단위를 정확히 맞추려면 "같은 기준"이 필요하다.
- 여러 화면에서 같은 말풍선 정책을 재사용하기 쉽다.
- 로그/실험/A-B 테스트 기준도 백엔드에서 통일하기 좋다.

## 권장 역할 분리

### 백엔드 역할

- `assistantMessage`를 유지한다.
- 추가로 `speechMode`, `speechSegments`를 함께 내려준다.
- 각 `speechSegment`는 "한 문장" 기준으로 분리한다.
- 필요 시 향후 `durationMs`, `audioUrl` 같은 메타데이터도 확장 가능하게 만든다.

### 프론트 역할

- `speechSegments`가 있으면 전체 문장을 한 번에 보여주지 않고 현재 segment만 표시한다.
- segment 단위로 TTS를 재생한다.
- segment 재생 완료 후 다음 segment로 넘어간다.
- `speechSegments`가 없으면 기존 `assistantMessage` 전체 표시 방식으로 fallback 한다.

## 권장 API 계약

기존 `assistantMessage`는 유지하고, 아래 필드를 추가한다.

```json
{
  "conversationId": 101,
  "status": "waiting_user_confirmation",
  "stage": "product_confirming",
  "assistantMessage": "김영희님, 뭐가 필요하세요? 천천히 말씀해 주세요.",
  "speechMode": "segmented",
  "speechSegments": [
    {
      "index": 0,
      "text": "김영희님, 뭐가 필요하세요?"
    },
    {
      "index": 1,
      "text": "천천히 말씀해 주세요."
    }
  ]
}
```

### 필드 제안

- `speechMode`
  - `"full_text"`: 기존과 동일하게 전체 텍스트 처리
  - `"segmented"`: `speechSegments` 순차 처리
- `speechSegments`
  - `index: int`
  - `text: str`
  - `audioUrl: Optional[str]` (지금은 생략 가능)
  - `durationMs: Optional[int]` (지금은 생략 가능)

## 권장 구현 방식

### 1. 백엔드 schema 확장

수정 대상:

- `backend/app/schemas/agent.py`

추가 제안:

```python
class SpeechSegment(BaseModel):
    index: int
    text: str
    audioUrl: Optional[str] = None
    durationMs: Optional[int] = None


class AgentResponse(BaseModel):
    ...
    assistantMessage: str
    speechMode: Optional[str] = None
    speechSegments: List[SpeechSegment] = []
```

## 2. 문장 분리 유틸 추가

권장 신규 파일:

- `backend/app/utils/speech_segments.py`

역할:

- `assistantMessage`를 화면 표시용 발화 단위로 분리
- 반환 형태는 `list[dict]` 또는 schema object list

예시 인터페이스:

```python
def build_speech_segments(text: str) -> list[dict]:
    ...
```

### 분리 규칙 제안

- 기본 기준은 문장 종결 부호
  - `.`, `?`, `!`
  - `요.`, `니다.`, `까요?`, `세요.`
- 빈 segment 제거
- 앞뒤 공백 제거
- segment 순서 유지
- 너무 짧은 문장 조각은 앞 문장과 합치지 말고 우선 그대로 둔다
- 숫자/단위/주소/전화번호는 불필요하게 끊지 않도록 한다

초기 버전은 "완벽한 자연어 분해기"가 아니라, deterministic한 문장 분리기로 시작하는 것이 현실적이다.

## 3. AgentResponse 생성 구간에서 segment 주입

수정 우선 대상:

- `backend/app/agent/mapper.py`
- `backend/app/services/agent_service.py`
- `backend/app/services/payment_service.py`
- 기타 `AgentResponse(...)`를 직접 만드는 서비스

원칙:

- `assistantMessage`를 만들 때 동일한 텍스트로 `speechSegments`도 생성한다.
- `speechMode`는 일단 `"segmented"`를 기본값으로 사용 가능하다.
- 음성/화면 순차 표시가 불필요한 특수 응답은 `"full_text"`도 가능하다.

예시:

```python
message = "결제가 완료되었어요. 주문이 접수되었어요."
segments = build_speech_segments(message)

return AgentResponse(
    ...,
    assistantMessage=message,
    speechMode="segmented",
    speechSegments=segments,
)
```

## 4. `/api/voice/tts`는 일단 유지

현재 단계에서는 `/api/voice/tts`를 바꾸지 않아도 된다.

즉, 1차 구현은 아래 흐름이면 충분하다.

1. 백엔드가 `speechSegments[].text`를 내려준다.
2. 프론트가 segment 텍스트를 하나씩 `/api/voice/tts`에 요청한다.
3. 프론트가 재생 완료 이벤트를 기준으로 다음 segment로 넘어간다.

이 방식의 장점:

- 백엔드 변경 범위를 최소화할 수 있다.
- 기존 TTS endpoint를 재사용할 수 있다.
- 프론트/백엔드 책임이 명확하다.

## 5. 향후 확장안

필요하면 2차로 아래 확장 가능:

- batch TTS endpoint 추가
  - 예: `/api/voice/tts/segments`
- segment별 오디오를 백엔드에서 미리 생성
- `durationMs` 추정값 또는 실제 길이 제공
- 특정 stage에서만 segmented mode 적용
- 말풍선 애니메이션과 TTS 타이밍을 더 정밀하게 동기화

## 백엔드 TODO

### 필수

- `AgentResponse` schema에 `speechMode`, `speechSegments` 추가
- 문장 분리 유틸 추가
- `mapper.py`에서 `assistantMessage` 기준 `speechSegments` 생성
- `agent_service.py`, `payment_service.py` 등 직접 `AgentResponse` 만드는 경로에도 동일 적용
- 응답 테스트 추가

### 권장

- 문장 분리 규칙 테스트 추가
- 빈 메시지/짧은 메시지/긴 메시지/상품명 포함 메시지 테스트 추가
- fallback 정책 정의
  - `speechSegments == []`이면 프론트는 `assistantMessage` 사용

## 테스트 항목

### API 계약 테스트

- `assistantMessage`가 있으면 `speechSegments`도 존재하는지
- `speechSegments[index]`가 정렬된 상태인지
- `speechSegments.text`를 공백 제거한 뒤 join 했을 때 원문 의미가 유지되는지

### 문장 분리 테스트

- `"김영희님, 뭐가 필요하세요?"`
  - 1개 segment
- `"결제가 완료되었어요. 주문이 접수되었어요."`
  - 2개 segment
- `"대추방울토마토 750g부터 보여드릴게요. 괜찮으면 장바구니에 담아볼까요?"`
  - 2개 segment
- `"주소는 서울 용산구 효창로 71길 107동 1206호 맞으세요?"`
  - 주소가 중간에서 부자연스럽게 끊기지 않는지 확인

## 프론트 예상 후속 작업

이번 문서는 백엔드 전달용이지만, 이후 프론트는 아래를 구현하게 된다.

- `shopping_flow_screen.dart`
  - 현재 segment index 상태 관리
  - segment별 말풍선 교체
  - segment별 TTS 순차 재생
- `smalltalk_screen.dart`
  - 동일 구조 적용 여부 검토
- fallback 처리
  - `speechSegments`가 없으면 기존 전체 문장 사용

## 오픈 질문

- 모든 stage에 segmented mode를 적용할지, 특정 stage만 적용할지
- 안내 멘트가 아주 짧은 경우에도 segment를 강제할지
- segment별 TTS를 매번 요청할지, 한 번에 미리 만들지
- 추후 accessibility/native TTS와도 같은 계약을 재사용할지

## 권장 결론

이번 요구사항은 "프론트에서 억지로 문장을 자르는 문제"가 아니라 "백엔드가 발화 단위를 내려주고, 프론트가 그 단위를 재생/표시하는 문제"로 보는 것이 맞다.

따라서 1차 구현 권장안은 아래와 같다.

1. 백엔드가 `assistantMessage + speechSegments`를 함께 내려준다.
2. 프론트가 `speechSegments`를 한 문장씩 표시한다.
3. 프론트가 각 segment를 `/api/voice/tts`로 순차 재생한다.
4. `assistantMessage`는 fallback 및 로그 용도로 유지한다.

---

# Backend Handoff: 수량 기본값 정책 + 장바구니 수량 조절

추가 작성일: 2026-08-06

## 목적

실제 쇼핑 흐름에서 사용자가 상품 수량을 따로 말하지 않았다면, 상품마다 매번 수량을 다시 묻지 않고 우선 `1개`를 장바구니에 담고 싶다.

그리고 사용자가 "더 담을 게 없다" 또는 "결제할래요" 단계로 들어왔을 때, 장바구니 화면에서 `- / 수량 / +` 버튼으로 최종 수량을 조절할 수 있게 만들고 싶다.

즉, 목표 정책은 아래와 같다.

1. 상품 선택 단계에서는 수량 미지정 시 기본값 `1`
2. 수량 확정은 장바구니 리뷰 단계에서 최종 조절
3. 상품마다 반복적으로 `몇 개 담아드릴까요?`를 강제하지 않음

## 현재 프론트 상태

### 이미 반영된 프론트 동작

- `frontend_v3/lib/features/shopping/screens/shopping_flow_screen.dart`
  - 상품 선택 단계에서 사용자가 "담아줘", "이걸로", "좋아", "주문해줘"처럼 수량 없는 확정 발화를 하면, 프론트가 임시로 `1개`를 자동 전송한다.
  - 장바구니 화면에는 `- / 수량 / +` UI가 추가되어 있다.
- `frontend_v3/lib/features/shopping/services/shopping_flow_service.dart`
  - live cart 조회 및 수량 변경 연동이 들어가 있다.
- `frontend_v3/lib/data/repositories/cart_repository.dart`
  - 현재 백엔드의 `GET /users/{userId}/cart`, `POST /carts/{cartId}/items`, `DELETE /carts/{cartId}/items/{cartItemId}`를 이용해 수량 증감이 되도록 우회 처리 중이다.

### 프론트 구현의 한계

현재 프론트는 백엔드 정책이 아직 바뀌지 않았기 때문에, "수량 미지정 시 1개"를 프론트가 대신 흉내 내고 있다.

이 방식은 화면상으로는 동작하지만, 정책의 진짜 기준이 프론트에 들어가 버려서 아래 문제가 있다.

- 음성/텍스트/버튼 확정 로직이 백엔드와 완전히 일치하지 않을 수 있다.
- 다른 클라이언트(Android native, accessibility flow 등)에서는 동일 정책이 자동 보장되지 않는다.
- 장바구니 수량 조절도 현재는 `delete + add` 우회라서 전용 API가 있으면 더 안정적이다.

## 현재 백엔드 상태

### 수량 관련 현재 정책

- `backend/vendor/ddalangoo-langgraph/src/prompts/intent_prompt.py`
  - 현재 prompt 규칙상 `quantity`는 명시적으로 언급된 경우만 채우고, 없으면 반드시 `null`이다.
- `backend/vendor/ddalangoo-langgraph/src/agents/response_agent.py`
  - 현재 `_build_confirm_pending_action(...)`는 수량이 없으면 `"주문을 원하시면 수량을 말씀해 주세요."` 쪽으로 유도한다.
- `backend/app/services/agent_service.py`
  - 실제 cart persist 시점에는 `state.get("quantity") or 1` 로 저장하는 경로가 이미 일부 존재한다.
  - 다만 상위 대화 정책에서 quantity confirm 단계를 먼저 강제하면, 프론트는 결국 수량 질문을 한 번 더 보게 된다.

### 장바구니 API 현재 상태

- 현재 존재:
  - `GET /api/users/{userId}/cart`
  - `POST /api/carts/{cartId}/items`
  - `DELETE /api/carts/{cartId}/items/{cartItemId}`
- 현재 없음:
  - `PATCH /api/carts/{cartId}/items/{cartItemId}` 같은 전용 수량 수정 API

## 백엔드에서 맞춰주면 좋은 최종 정책

## 1. 상품 확정 시 수량이 없으면 기본값 1로 처리

원하는 정책:

- 사용자가 상품 추천을 보고 "이걸로", "장바구니에 담아줘", "좋아", "주문해줘"처럼 확정 의사를 말했는데 수량을 따로 말하지 않았다면:
  - `quantity = 1`로 간주
  - `quantity_confirm` 단계로 보내지 않음
  - 바로 cart 반영으로 진행

중요:

- NLU 단계에서는 여전히 `quantity = null`을 유지해도 괜찮다.
- 다만 플로우 제어 단계에서 `product_confirm + confirm + quantity is null` 조합이면, 이를 `기본 수량 1` 정책으로 승격하면 된다.

즉, 아래처럼 보는 것이 좋다.

- intent 추출 규칙:
  - "수량이 언급되지 않았음" = `null`
- business policy:
  - "상품 확정인데 수량이 null이면" = `1개로 진행`

## 2. 수량 질문은 예외 상황에서만 사용

`몇 개 담아드릴까요?`는 항상 묻는 기본 플로우가 아니라, 아래 예외 상황에서만 쓰는 것이 좋다.

- 사용자가 처음부터 명시적으로 수량 변경을 요구한 경우
- 옵션/묶음 구조상 수량 확인이 꼭 필요한 상품
- backend rule상 orderable 하되, 특정 플랫폼 자동화에서 수량 확인이 필수인 경우

그 외 일반 상품은 기본적으로:

1. 후보 확정
2. 1개 장바구니 담기
3. 장바구니 화면에서 최종 수량 조절

이 흐름으로 통일되면 좋다.

## 3. 장바구니 화면을 최종 수량 조절 소스로 사용

원하는 정책:

- 사용자가 "더 구매할래요"가 아니라 "결제할래요", "이제 됐어", "더 없어" 쪽으로 가면
  - 현재 cart 전체를 기준으로 장바구니 리뷰 화면을 보여준다.
- 이 단계에서는 line item별로 수량 증감이 가능해야 한다.

프론트가 기대하는 최소 데이터:

- `cartId`
- 각 item의 `cartItemId`
- `productId`
- `productOptionId` (없으면 null)
- `quantity`
- `unitPrice`

## 권장 API 추가

가장 권장하는 방식은 전용 수량 수정 API를 추가하는 것이다.

예시:

```http
PATCH /api/carts/{cartId}/items/{cartItemId}
Content-Type: application/json

{
  "quantity": 3
}
```

응답 예시:

```json
{
  "cartItemId": 501,
  "productId": 23,
  "productOptionId": 7,
  "productName": "대추방울토마토 750g",
  "optionText": "1팩",
  "unitPrice": 8900,
  "quantity": 3,
  "totalPrice": 26700
}
```

또는 full cart를 반환해도 괜찮다.

```json
{
  "cartId": 77,
  "userId": 1,
  "status": "active",
  "items": [...]
}
```

### 왜 PATCH가 필요한가

지금 프론트는 수량 감소 시 `기존 cart item 삭제 -> 새 수량으로 다시 add` 하는 우회를 하고 있다.

이 방식은 임시로는 가능하지만, 아래 이유로 전용 수정 API가 더 낫다.

- cart item identity가 매번 바뀔 수 있다.
- 추천 후보 snapshot 기반 item과 일반 product 기반 item을 같은 규칙으로 다루기 어렵다.
- audit/log/event 추적이 불필요하게 복잡해진다.
- 나중에 accessibility/native 쪽에서도 같은 API를 재사용하기 쉽다.

## 권장 백엔드 구현 포인트

## A. confirm 처리 정책 수정

수정 후보:

- `backend/vendor/ddalangoo-langgraph/src/agents/response_agent.py`
- `backend/app/services/agent_service.py`
- 필요 시 router / mapper 레벨

권장 규칙:

- `pending_action == product_confirm`
- user intent == `confirm`
- `quantity == null`

이면:

- `quantity = 1`
- pending action을 quantity confirm으로 바꾸지 않음
- 바로 cart persist 단계 진행

## B. cart schema / router 확장

수정 후보:

- `backend/app/schemas/cart.py`
- `backend/app/routers/cart.py`
- `backend/app/services/cart_service.py`
- `backend/app/repositories/cart_repository.py`

추가 제안:

```python
class CartItemQuantityUpdateRequest(BaseModel):
    quantity: int
```

```python
@router.patch("/carts/{cartId}/items/{cartItemId}")
async def update_cart_item_quantity(...):
    ...
```

repository/service 정책:

- `quantity <= 0`이면 reject 또는 delete 정책 중 하나로 명확히 통일
- 권장안:
  - `PATCH quantity=0`은 삭제로 간주하거나
  - `PATCH`는 1 이상만 허용하고 삭제는 기존 `DELETE`를 사용

둘 중 하나를 명확히 계약으로 정하면 된다.

## C. AgentResponse.cart payload 보강

현재 프론트는 장바구니 리뷰 화면에서 각 item을 안정적으로 조절하려면, 응답의 `cart` payload에 item 단위 식별자가 충분히 들어오는 것이 좋다.

권장 형태:

```json
{
  "cart": {
    "cartId": 77,
    "status": "active",
    "items": [
      {
        "cartItemId": 501,
        "productId": 23,
        "productOptionId": 7,
        "productName": "대추방울토마토 750g",
        "optionText": "1팩",
        "quantity": 1,
        "unitPrice": 8900,
        "totalPrice": 8900
      }
    ]
  }
}
```

## 테스트 항목

### 상품 확정 기본 수량

- `"토마토 담아줘"`:
  - 수량 질문 없이 1개 장바구니 반영되는지
- `"삼겹살 2개 담아줘"`:
  - 명시 수량 2가 유지되는지
- `"이걸로 할래"`:
  - 현재 선택 상품이 1개로 담기는지

### 장바구니 수량 변경

- `+` 1회:
  - quantity가 1 증가하는지
- `-` 1회:
  - quantity가 1 감소하는지
- quantity가 1일 때 `-`:
  - 삭제 정책이 기대대로 동작하는지

### 결제 직전 흐름

- 더 이상 담을 상품이 없다고 한 뒤:
  - 장바구니 리뷰가 최종 수량 기준이 되는지
- 결제 단계 진입 후:
  - order/payment 생성 금액이 cart의 최종 수량과 일치하는지

## 권장 결론

현재 프론트는 사용자 경험을 맞추기 위해 "수량 미지정 시 1개"를 임시로 프론트에서 자동 처리하고 있다.

하지만 이 정책은 본질적으로 UI 규칙이 아니라 쇼핑 business policy에 가깝다.

따라서 최종적으로는:

1. 백엔드가 상품 확정 + 수량 미지정을 `1개 기본값`으로 처리하고
2. 장바구니 전용 수량 수정 API를 제공하고
3. 프론트는 그 정책을 그대로 보여주는 역할만 하게 만드는 것이 가장 안정적이다.

---

# Backend/Native Handoff: 플랫폼 확인 화면 진행 상태 값

작성일: 2026-08-07

## 목적

플랫폼 확인 화면에서:

- 상단 카드 = 딸랑구 안내 문구
- 하단 배너 = 접근성/자동화 진행 상황

처럼 역할을 분리하고 싶다.

프론트는 현재 mock-data로는 진행 상황을 흉내 내고 있다. 하지만 실제 기기에서는 Android accessibility/native 쪽이 아래 상태 값을 내려줘야 더 정확한 진행 로그를 보여줄 수 있다.

## 지금 프론트에서 이미 가능한 것

- 확인된 쇼핑 앱 수
- 마지막으로 감지한 앱 패키지명
- 접근성 서비스 연결 여부

즉, 현재도 아래 정도는 표시 가능하다.

- `쇼핑 앱 후보 5개 중 3개 확인`
- `마지막으로 네이버 앱 확인`
- `접근성 서비스 연결됨`

하지만 아래 값은 아직 직접 알 수 없다.

- 휴대폰 전체 설치 앱 수
- 지금까지 전체 앱 몇 개를 스캔했는지
- 쇼핑 앱 탐색의 현재 단계

## 백엔드/네이티브에서 추가로 내려주면 좋은 값

권장 전달 경로:

- `getAutomationStatus()` 응답에 추가

권장 필드:

```json
{
  "serviceConnected": true,
  "lastMessage": "앱을 살펴보고 있어요.",
  "lastPackageName": "com.nhn.android.search",
  "totalInstalledAppCount": 34,
  "scannedAppCount": 12,
  "detectedShoppingAppCount": 1,
  "currentPhase": "inspecting_apps"
}
```

## 필드 설명

- `totalInstalledAppCount: int`
  - 기기에 설치된 전체 앱 수
  - 예: `34`
- `scannedAppCount: int`
  - 현재까지 실제로 살펴본 앱 수
  - 예: `12`
- `detectedShoppingAppCount: int`
  - 현재까지 쇼핑 앱으로 분류된 앱 수
  - 예: `1`
- `currentPhase: string`
  - 현재 단계
  - 예:
    - `loading_apps`
    - `inspecting_apps`
    - `matching_shopping_apps`
    - `completed`
- `lastPackageName: string`
  - 가장 최근에 확인한 앱 package name
- `lastMessage: string`
  - 네이티브/자동화 쪽에서 전달하고 싶은 보조 진행 문구

## 프론트에서 이 값으로 만들고 싶은 UX

예시 문구:

- `김영희님의 폰에 깔린 앱이 총 34개예요.`
- `앱을 하나씩 살펴보고 있어요.`
- `34개 앱 중 12개를 살펴봤어요.`
- `34개 앱 중 3개의 쇼핑 앱이 확인되었어요.`
- `마지막으로 네이버 앱을 확인했어요.`

즉, "딸랑구가 말하는 배너"가 아니라 "실시간 진행 로그 카드"처럼 쓰고 싶다.

## 프론트 fallback 정책

위 값이 없더라도 화면은 동작해야 한다.

fallback 우선순위:

1. `totalInstalledAppCount`, `scannedAppCount`, `detectedShoppingAppCount`가 있으면 진행 로그 중심으로 표시
2. 없으면 현재처럼 `지원하는 쇼핑 앱 후보 수 / 확인된 쇼핑 앱 수 / 마지막 감지 앱` 기준으로 표시
3. 그것도 없으면 정적 안내 문구로 fallback

## 구현 요청 요약

네이티브 또는 백엔드에서 `getAutomationStatus()`에 아래 값들을 추가해주면 좋다.

- `totalInstalledAppCount`
- `scannedAppCount`
- `detectedShoppingAppCount`
- `currentPhase`
- `lastPackageName`
- `lastMessage`

이 값들이 있으면 프론트는 플랫폼 확인 화면의 하단 배너를 더 정확한 진행 상태 카드로 바꿔서 보여줄 수 있다.
