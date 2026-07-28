# State 구조

> 이 문서는 실제 `src/state/schema.py`/`src/state/node_inputs.py`와 동기화된
> 스냅샷이다.

## 결정 — 지금은 Root/Subgraph 전면 분리를 하지 않는다

`ShoppingState` 하나를 유지하는 이유는 실제 코드를 근거로 검토한 결과다:

- 실행 그래프는 지금도 `StateGraph(ShoppingState)` 하나뿐이고 Subgraph는 없다(`src/graph/builder.py`).
- Payment를 Subgraph로 분리하려던 예전 시도(`PaymentState`, `payment_flow()`, `bridge_shopping_to_payment`/`bridge_payment_to_shopping`)가 코드에 남아있었지만 실제 그래프에 연결된 적이 없었고, `selected_product: dict` 단수 구조라 실제 `payment_agent_node`가 지원하는 **장바구니(다중 상품)**와도 안 맞았다 — 그대로 되살리면 회귀였다. **삭제했다**(3번 참고).
- 외부 API 계약(`backend/app/agent/mapper.py:state_to_response`)이 `ShoppingState`의 수십 개 필드(`recommendations`, `cart`, `order`, `payment`, `deliveryAddress`, `pendingConfirmation`, `uiCommand`, `asyncStatus` 등)를 flat하게 직접 읽는다 — Root/Subgraph로 쪼개면 이 계약을 다시 투영하거나 mapper.py 자체를 재설계해야 하는데, 지금 그럴 만큼 확실한 이득이 없다.

대신 진행한 것: **노드별 Read/Write State 계약을 타입으로 좁혀서**(아래 2번) Subgraph 없이도 각 노드가 실제로 뭘 읽고 쓰는지 명시하고, 결합도를 낮췄다. 이건 나중에 정말 Subgraph가 필요해지면 그 입력 스키마의 초안이 된다.

## 공통 타입

```python
Stage = Literal[
    "idle", "searching", "product_confirming", "cart_shopping",
    "recipe_planning", "payment_processing", "payment_password_required",
    "completed", "failed",
]

Intent = Literal[
    "buy", "reorder", "confirm", "deny", "next", "refine",
    "compare_platforms", "quantity_change", "address_change",
    "option_select", "ask", "cancel", "unclear", "smalltalk",
]

Condition = Literal["최저가", "가성비", "빠른배송", "인기순", "무료배송", "리뷰좋은"]

PendingActionType = Literal[
    "product_confirm", "product_select", "clarification", "payment_confirm",
    "address_confirm", "address_required", "price_change_confirm",
    "continue_shopping", "what_to_buy", "no_more_products", "cart_review",
    "ingredient_confirm", "payment_method_confirm", "payment_password",
]

class PendingAction(TypedDict, total=False):
    type: PendingActionType
    payload: dict[str, Any]
    message: str
    expires_at: Optional[str]
```

## 1. ShoppingState — 그래프 전체가 공유하는 유일한 State

```python
class ShoppingState(TypedDict):
    messages: Annotated[list, add_messages]

    stage: Stage
    intent: Optional[Intent]
    last_agent: Optional[str]
    error: Optional[str]

    confidence: Optional[float]
    immediate_response: Optional[str]
    needs_clarification: bool
    clarification_reason: Optional[str]

    keywords: list[str]
    exclude_keywords: list[str]
    negative_constraints: list[str]
    quantity: Optional[int]
    condition: Optional[Condition]

    override_platform: Optional[str]
    target_platforms: list[str]
    tried_platforms: list[str]
    selected_platform: Optional[str]

    search_results: list[dict[str, Any]]
    scored_products: list[dict[str, Any]]
    recommended_products: list[dict[str, Any]]
    current_product_index: int
    selected_product: Optional[dict[str, Any]]
    product_url: Optional[str]
    explanation: Optional[str]
    highlight_specs: list[str]

    pending_action: Optional[PendingAction]

    cart: Optional[dict[str, Any]]
    order: Optional[dict[str, Any]]
    payment: Optional[dict[str, Any]]
    checkout_session: Optional[dict[str, Any]]

    session_id: str
    conversation_id: Optional[int]
    user_id: str

    storage_state_path: Optional[str]
    cart_items: list[dict[str, Any]]

    recipe_dish: Optional[str]
    recipe_people: Optional[int]
    recipe_items: list[dict[str, Any]]
    current_recipe_item_index: int

    recommendation_context: Optional[dict[str, Any]]
    reorder_resolution: Optional[dict[str, Any]]

    current_option_value: Optional[str]
    address_text: Optional[str]
    tool_calls: Optional[list[dict[str, Any]]]
    tool_results: Optional[dict[str, Any]]
    conversation_summary: Optional[str]
    order_id: Optional[str]
```

`recommendation_context`는 **ShoppingState가 유일한 source of truth**다. 예전엔
`context_agent`가 LangGraph Store에도 같은 값을 write했는데, 그 값을 읽는
코드가 어디에도 없어서 순수 낭비였다 — 제거했다. `build_graph()`의 Store
wiring(`InMemoryStore` 생성/`compile(store=...)`) 자체도 함께 제거했다 —
Store를 쓰는 노드가 이제 하나도 없기 때문이다. 세션 간 재사용이 실제로
필요해지면 그때 요구사항과 함께 다시 도입한다.

`completed_purchase` 필드는 삭제했다 — `ShoppingState`에 선언된 적도 없고
어디서도 write되지 않는 죽은 참조였다(`context_agent`가 읽으려 시도했지만
실제 구매이력 저장은 `payment_agent_node` → `mock_place_order` →
`mock_save_purchase_history` 경로로 이미 이루어지고 있어서 기능 손실 없음).
연쇄적으로 `context_agent._save_purchase_history_from_completed`와
`db_client.save_purchase_history_from_completed`(호출부가 이거 하나뿐이었음)도
같이 제거했다.

## 2. 노드별 Read/Write State 계약 (`src/state/node_inputs.py`)

그래프 State 자체는 `ShoppingState` 하나로 유지하되(Subgraph 아님), 각 노드
함수의 시그니처는 **입력**은 실제로 읽는 필드만 담은 좁은 TypedDict로,
**반환값**은 실제로 쓰는 필드만 담은 `total=False` TypedDict로 선언한다 —
`좁은 Read 타입 → Node → 명시된 Partial Update`로 대칭을 이룬다.

TypedDict은 구조적 타이핑이라 더 큰 dict(=ShoppingState 전체)를 넘겨도
런타임에는 문제없다. **이건 노드별 최소 Read 계약을 명시(=노드 의존 필드
타입 명시)하는 정적 문서화 장치이지, 런타임에 다른 State 필드로의 접근을
차단하는 보안 경계가 아니다** — 민감정보는 애초에 ShoppingState 자체에
넣지 않아야 한다.

| 노드 | 입력 타입 | 반환 타입 | Read 필드 | 주요 Write 필드 |
|---|---|---|---|---|
| `intent_agent_node` | `IntentAgentInput` | `IntentAgentUpdate` | messages, stage, pending_action, keywords, quantity, recipe_dish, recipe_people, user_id | intent, keywords, exclude_keywords, quantity, condition, recipe_dish/people, needs_clarification, clarification_reason, confidence, immediate_response |
| `context_agent_node` | `ContextAgentInput` | `ContextAgentUpdate` | stage, intent, user_id, keywords, exclude_keywords, messages | recommendation_context, keywords, exclude_keywords, conversation_summary(완료 시) |
| `product_agent_node` | `ProductAgentInput` | `ProductAgentUpdate` | intent, keywords, exclude_keywords, condition, current_product_index, recommended_products, recommendation_context | search_results, selected_product, product_url, recommended_products, current_product_index, stage, error, pending_action |
| `response_agent_node` | `ResponseAgentInput` | `ResponseAgentUpdate` | intent, keywords, condition, recommendation_context, recommended_products, current_product_index, selected_product, messages, stage, quantity, user_id | explanation, pending_action, stage, needs_clarification (+ ShoppingState에 없는 애드혹 필드 reflection_passed/haiku_fallback/reflection_reason) |
| `reorder_agent_node` | `ReorderAgentInput` | `ReorderAgentUpdate` | pending_action, user_id, keywords, messages | selected_product, product_url, pending_action, stage, error, search_results |
| `recipe_agent_node` | `RecipeAgentInput` | `RecipeAgentUpdate` | stage, intent, recipe_dish, recipe_people, recipe_items, current_recipe_item_index, messages | recipe_items, current_recipe_item_index, stage, pending_action, intent, keywords, quantity |
| `smalltalk_agent_node` | `SmalltalkAgentInput` | `SmalltalkAgentUpdate` | user_id, messages | explanation, immediate_response, pending_action, stage |
| `payment_agent_node` | `PaymentAgentInput` | `PaymentAgentUpdate` | stage, pending_action, user_id, selected_product, keywords, quantity, intent, address_text, conversation_id | stage, selected_product, cart_items, pending_action, order_id |
| `respond_node` | `RespondNodeInput` | `dict`(*) | stage, intent, immediate_response, explanation, pending_action, needs_clarification, clarification_reason, error | messages, pending_action(클리어) |
| `cancel_node` | `CancelNodeInput` | `dict`(*) | cart_items | stage, intent, pending_action, keywords, selected_product 등 리셋 |

(*) `respond_node`/`cancel_node`는 제어 노드라 Write 타입까지는 안 만들었다 — 필요해지면 추가.

같은 파일의 private 헬퍼(`_extract_user_input` 등)는 기존처럼 `ShoppingState`를
받는다 — churn 대비 이득이 작아 이번 범위에서는 안 건드렸다.

## 3. 삭제한 것 — Dormant Payment 구조

`PaymentState`, `PaymentStage`, `PaymentStatus`, `bridge_shopping_to_payment`,
`bridge_payment_to_shopping`(전부 `schema.py`)와 `src/payment/flow.py`
(`payment_flow()`, `fail_payment()`)를 **완전히 삭제**했다. Payment를
Subgraph로 분리하려던 예전 시도의 흔적이었는데:

- `builder.py`는 이걸 전혀 안 쓰고 `payment/node.py`의 플랫 `payment_agent_node`만 사용
- 유일한 호출부는 이미 깨져있던 `tests/test_payment_flow.py`(`wait_for_user_action`을 import하는데 애초에 존재하지 않는 이름 — 이번 세션 이전부터 broken)뿐
- `selected_product: dict` 단수 구조라 실제 장바구니(다중 상품) 지원과도 안 맞았음

**남겨둔 것**: `MemoryState` + `bridge_memory_to_shopping`은 `tests/test_graph_invoke.py`가
실제로 참조하는 살아있는 테스트가 있어서 이번 범위에서는 안 건드렸다 —
비슷한 패턴(선언은 있지만 프로덕션에서 안 쓰임)이라 추후 정리 후보로만 기록.

다시 Payment Subgraph를 시도한다면(포트폴리오 설명용):

> 초기에는 Payment Subgraph를 검토했지만 장바구니·interrupt·외부 API 계약의
> 회귀 위험 때문에 현재 flat workflow를 유지했다.

## 4. 이번에 정리한 것 (전체 요약)

1. `context_agent`의 `recommendation_context` Store write/read(미사용) 제거 — ShoppingState가 유일한 source of truth로 명시.
2. `completed_purchase` 죽은 참조 제거 (`context_agent`, `db_client.save_purchase_history_from_completed`).
3. `build_graph()`의 Store wiring(`InMemoryStore` 생성, `compile(store=...)`, `test_graph_invoke.py`의 `create_test_graph()`) 전체 제거.
4. Dormant Payment 구조(`PaymentState`/`payment_flow`/`bridge_shopping_to_payment`/`bridge_payment_to_shopping`, `src/payment/flow.py`) 전체 삭제.
5. 8개 도메인 노드 + `respond_node`/`cancel_node`에 좁은 Read 타입(`*Input`) 적용, 8개 도메인 노드에는 Write 타입(`*Update`)까지 대칭으로 적용(`src/state/node_inputs.py`).
6. `src/payment/subgraph.py` → `src/payment/node.py` 파일명 정리(실제로는 LangGraph subgraph가 아니라 플랫 노드 함수였음) — `builder.py`/`test_cancel.py`/`test_payment_cart_guard.py`/`test_refactor.py` import 갱신.

## 5. 보류한 것

- Recommendation/Recipe Subgraph 전환, `backend/app/agent/mapper.py` 전면 재설계 — 외부 API 계약 리스크가 커서 지금은 보류.
- `MemoryState`/`bridge_memory_to_shopping` 정리 — 살아있는 테스트가 있어 이번 범위 밖.
