Router

```powershell
from typing import Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

# ══════════════════════════════════════════════
# Router
# ══════════════════════════════════════════════

RouteName = Literal[
    "memory_agent",
    "platform_agent",
    "product_agent",
    "payment_agent",
    "respond",
    "interrupt_payment",
    "end",
]

def route(state: ShoppingState) -> RouteName:
    """
    Intent + Stage 기반 라우팅.
    원칙:
    1. clarification 우선
    2. cancel 우선
    3. payment_processing이면 Payment Subgraph로 위임
    4. product_confirming에서는 intent별 분기
    5. idle/searching에서는 intent 기반 분기
    """

    intent = state.get("intent")
    stage = state.get("stage", "idle")
    confidence = state.get("confidence") or 0.0
    needs_clarification = state.get("needs_clarification", False)

    # ── 1. 명확성 검사 ──
    if needs_clarification or confidence < 0.5 or intent == "unclear":
        return "respond"

    # ── 2. cancel은 어디서든 우선 처리 ──
    if intent == "cancel":
        if stage == "payment_processing":
            return "interrupt_payment"
        return "end"

    # ── 3. 결제 진행 중이면 Payment Subgraph가 처리 ──
    # option_select, address_change, quantity_change, confirm/deny 등은
    # payment_agent 내부 pending_action 기준으로 처리
    if stage == "payment_processing":
        return "payment_agent"

    # ── 4. 상품 확인 단계 ──
    if stage == "product_confirming":
        if intent == "confirm":
            return "payment_agent"

        if intent in ("deny", "next", "ask"):
            return "product_agent"

        if intent in ("refine", "compare_platforms"):
            return "platform_agent"

        if intent in ("quantity_change", "address_change", "option_select"):
            # 아직 결제 단계가 아니므로 맥락상 바로 처리하지 않음
            return "respond"

        return "respond"

    # ── 5. 검색 중 ──
    if stage == "searching":
        if intent == "cancel":
            return "end"

        if intent in ("refine", "compare_platforms"):
            return "platform_agent"

        if intent == "ask":
            return "respond"

        return "respond"

    # ── 6. idle / 기본 Intent 기반 라우팅 ──
    routing_map = {
        "buy": "platform_agent",
        "reorder": "memory_agent",
        "compare_platforms": "platform_agent",
        "refine": "platform_agent",
        "ask": "product_agent",
        "next": "product_agent",

        # pending_action 없는 confirm/deny는 Intent Agent에서 unclear 처리되는 게 원칙
        "confirm": "respond",
        "deny": "respond",

        # 결제 전용 intent는 idle에서는 직접 처리하지 않음
        "option_select": "respond",
        "quantity_change": "respond",
        "address_change": "respond",
    }

    return routing_map.get(intent, "respond")

# ══════════════════════════════════════════════
# Orchestrator Graph
# ══════════════════════════════════════════════

def build_graph(checkpointer: PostgresSaver, store: PostgresStore):
    """LangGraph Orchestrator Graph 구성"""

    builder = StateGraph(ShoppingState)

    # ── 노드 등록 ──
    builder.add_node("wait_for_input", wait_for_input_node)
    builder.add_node("intent_agent", intent_agent_node)
    builder.add_node("memory_agent", memory_agent_node)
    builder.add_node("platform_agent", platform_agent_node)
    builder.add_node("product_agent", product_agent_node)
    builder.add_node("payment_agent", payment_agent_node)
    builder.add_node("respond", respond_node)
    builder.add_node("interrupt_payment", interrupt_payment_node)

    # ── 진입점 ──
    builder.set_entry_point("wait_for_input")

    # ── 사용자 입력 대기 후 Intent 분석 ──
    builder.add_edge("wait_for_input", "intent_agent")

    # ── Intent Agent 이후 Router 분기 ──
    builder.add_conditional_edges(
        "intent_agent",
        route,
        {
            "memory_agent": "memory_agent",
            "platform_agent": "platform_agent",
            "product_agent": "product_agent",
            "payment_agent": "payment_agent",
            "respond": "respond",
            "interrupt_payment": "interrupt_payment",
            "end": END,
        },
    )

    # ── 각 Agent 이후 응답 생성 ──
    builder.add_edge("memory_agent", "respond")
    builder.add_edge("platform_agent", "respond")
    builder.add_edge("product_agent", "respond")
    builder.add_edge("payment_agent", "respond")
    builder.add_edge("interrupt_payment", "respond")

    # ── respond 이후 계속 진행 여부 판단 ──
    def after_respond(state: ShoppingState) -> Literal["wait_for_input", "end"]:
        stage = state.get("stage", "idle")
        error = state.get("error")

        if stage in ("completed", "failed"):
            return "end"

        if error and "fatal" in error.lower():
            return "end"

        return "wait_for_input"

    builder.add_conditional_edges(
        "respond",
        after_respond,
        {
            "wait_for_input": "wait_for_input",
            "end": END,
        },
    )

    return builder.compile(
        checkpointer=checkpointer,
        store=store,
        interrupt_before=["wait_for_input"],
    )

# ══════════════════════════════════════════════
# Node Stubs
# ══════════════════════════════════════════════

def wait_for_input_node(state: ShoppingState) -> dict:
    """
    사용자 입력 대기 노드.
    interrupt_before=["wait_for_input"] 설정으로 이 지점에서 항상 멈춘다.
    """
    return {}

def intent_agent_node(state: ShoppingState) -> dict:
    """
    Intent Agent 호출.
    반환값:
    - intent
    - keywords
    - exclude_keywords
    - negative_constraints
    - quantity
    - condition
    - target_platforms
    - override_platform
    - current_option_value
    - address_text
    - needs_clarification
    - clarification_reason
    - confidence
    - immediate_response
    """
    pass

def memory_agent_node(state: ShoppingState) -> dict:
    """
    Memory Agent.
    역할:
    - reorder intent 처리
    - 구매 이력 조회
    - 추천 retrieval context 생성
    - 필요 시 platform_agent/product_agent에 넘길 context 준비

    주의:
    - ShoppingState에 user_context 전체를 주입하지 않는다.
    - 필요한 결과만 messages 또는 별도 context payload로 전달한다.
    """
    pass

def platform_agent_node(state: ShoppingState) -> dict:
    """
    Platform Agent.
    역할:
    - 플랫폼 선택
    - Meta-MCP search_product 호출
    - 검색 결과 정규화
    - search_results 갱신

    Payment 관련 처리는 하지 않는다.
    """
    pass

def product_agent_node(state: ShoppingState) -> dict:
    """
    Product Agent.
    역할:
    - 상품 비교/랭킹
    - 추천 상품 선택
    - 상품 관련 질문 답변
    - explanation 생성
    - pending_action={"type": "product_confirm"} 설정

    상품 검색과 결제 처리는 하지 않는다.
    """
    pass

def payment_agent_node(state: ShoppingState) -> dict:
    """
    Payment Subgraph 진입 노드.
    역할:
    - bridge_shopping_to_payment()로 PaymentState 생성
    - Payment Subgraph 실행
    - bridge_payment_to_shopping()으로 결과만 ShoppingState에 반영

    옵션/주소/checkout/playwright/retry는 PaymentState 내부에서만 관리한다.
    """
    pass

def respond_node(state: ShoppingState) -> dict:
    """
    사용자에게 보낼 TTS 메시지 생성.
    ShoppingState 기준의 stage와 pending_action만 사용한다.
    Payment 내부 세부 상태는 pending_action.message로 받는다.
    """

    stage = state.get("stage", "idle")
    immediate = state.get("immediate_response")
    explanation = state.get("explanation")
    pending_action = state.get("pending_action") or {}

    # 1. clarification 우선
    if state.get("needs_clarification"):
        msg = immediate or state.get("clarification_reason") or "조금 더 자세히 말씀해 주세요."

    # 2. pending_action에 명시 메시지가 있으면 우선 사용
    elif pending_action.get("message"):
        msg = pending_action["message"]

    # 3. 상품 확인 단계
    elif stage == "product_confirming":
        msg = explanation or "이 상품으로 주문할까요?"

    # 4. 결제 진행 단계
    elif stage == "payment_processing":
        msg = immediate or "결제를 계속 진행할까요?"

    # 5. 완료/실패
    elif stage == "completed":
        msg = "주문이 완료되었습니다."

    elif stage == "failed":
        msg = state.get("error") or "처리 중 문제가 발생했습니다."

    # 6. 기본 응답
    else:
        msg = immediate or "무엇을 도와드릴까요?"

    return {
        "messages": [{"role": "assistant", "content": msg}]
    }

def interrupt_payment_node(state: ShoppingState) -> dict:
    """
    결제 중 cancel 처리.
    실제 checkout/order/payment rollback은 Payment Subgraph 또는 service layer에서 처리해야 한다.
    """

    return {
        "stage": "idle",
        "error": None,
        "pending_action": None,
        "last_agent": "interrupt_payment",
        "messages": [
            {
                "role": "assistant",
                "content": "결제를 취소했습니다.",
            }
        ],
    }
```