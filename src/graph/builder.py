"""
Orchestrator Graph Builder.

LangGraph StateGraph 구성:
- session_start → 신규·미온보딩유저(메시지 0개): smalltalk_agent가 먼저
  선제 인사 → respond → wait_for_input
- session_start → 기존/온보딩완료 유저: wait_for_input
- 이후 턴: wait_for_input → intent_agent/smalltalk_agent(route_entry) →
  route() → {agents} → respond → after_respond()
- interrupt_before=["wait_for_input"] (human-in-the-loop)
- MemorySaver (standalone 기본; production: PostgresSaver)

Store(장기 메모리)는 현재 안 쓴다 — 예전엔 context_agent가 recommendation_context를
Store에도 write했는데 그걸 읽는 코드가 없어서 제거했고, 그 이후로 Store를
실제로 쓰는 노드가 하나도 없어서 wiring 자체를 뺐다. 장기 메모리가 실제로
필요해지면 그때 요구사항과 함께 다시 도입한다.
"""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.state.schema import ShoppingState
from src.graph.router import (
    route,
    route_entry,
    route_session_start,
    after_respond,
    after_context_agent,
    after_reorder_agent,
    after_product_agent,
    after_response_agent,
    after_recipe_agent,
    after_payment_agent,
    after_fallback_orchestrator,
)
from src.agents.intent_agent import intent_agent_node, intent_error_handler
from src.agents.context_agent import context_agent_node
from src.agents.reorder_agent import reorder_agent_node
from src.agents.product_agent import product_agent_node
from src.agents.response_agent import response_agent_node
from src.agents.nodes import (
    session_start_node,
    wait_for_input_node,
    reset_turn_observability_node,
    respond_node,
    cancel_node,
    ask_what_to_buy_node,
)
from src.agents.recipe_agent import recipe_agent_node
from src.agents.smalltalk_agent import smalltalk_agent_node, smalltalk_error_handler
from src.agents.fallback_orchestrator import fallback_orchestrator_node
from src.payment.node import payment_agent_node
from src.utils.retry import NODE_RETRY_POLICY

# intent_agent(route)와 fallback_orchestrator(after_fallback_orchestrator, recover
# 시 route()를 그대로 재호출)가 도달할 수 있는 목적지 집합은 동일해야 한다 —
# 하나로 공유해서 둘이 따로따로 갱신되다 어긋나는 걸 방지한다.
_ROUTE_DESTINATIONS = {
    "context_agent": "context_agent",
    "reorder_agent": "reorder_agent",
    "product_agent": "product_agent",
    "response_agent": "response_agent",
    "recipe_agent": "recipe_agent",
    "payment_agent": "payment_agent",
    "smalltalk_agent": "smalltalk_agent",
    "ask_what_to_buy": "ask_what_to_buy",
    "respond": "respond",
    "cancel": "cancel",
    "fallback_orchestrator": "fallback_orchestrator",
    "end": END,
}


def build_graph(checkpointer=None):
    """
    LangGraph Orchestrator Graph 구성.

    Parameters
    ----------
    checkpointer : 체크포인터 (기본: MemorySaver — in-memory)
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(ShoppingState)

    builder.add_node("session_start", session_start_node)
    builder.add_node("wait_for_input", wait_for_input_node)
    builder.add_node("reset_turn_observability", reset_turn_observability_node)
    # intent_agent/smalltalk_agent: 단일 LLM 호출 중심 + 부수효과 없음 → Node 전체
    # RetryPolicy 적용. 소진 시(또는 재시도 대상이 아닌 예외) error_handler가
    # 축소 응답으로 연결한다(docs/resilience_plan.md Phase 1 참고).
    builder.add_node("intent_agent", intent_agent_node, retry_policy=NODE_RETRY_POLICY, error_handler=intent_error_handler)
    builder.add_node("context_agent", context_agent_node)
    builder.add_node("reorder_agent", reorder_agent_node)
    builder.add_node("product_agent", product_agent_node)
    builder.add_node("response_agent", response_agent_node)
    builder.add_node("recipe_agent", recipe_agent_node)
    builder.add_node("smalltalk_agent", smalltalk_agent_node, retry_policy=NODE_RETRY_POLICY, error_handler=smalltalk_error_handler)
    # payment_agent: 장바구니/주문 등 부수효과가 있어 멱등성 키 없이는 자동
    # Retry를 붙이지 않는다(docs/resilience_plan.md Phase 1-6/4 참고).
    builder.add_node("payment_agent", payment_agent_node)
    builder.add_node("respond", respond_node)
    builder.add_node("ask_what_to_buy", ask_what_to_buy_node)
    builder.add_node("cancel", cancel_node)
    # fallback_orchestrator: route()가 needs_clarification/confidence/unclear로
    # 막힌 게 반복되면(fallback_stuck_turns>=1) 여기로 보낸다. 정상 흐름에서는
    # 절대 안 거쳐가는 노드 — LLM 호출 자체가 try/except로 감싸져 있어(내부에서
    # retry_call 사용) 전체 Node RetryPolicy는 안 붙인다(intent_agent/smalltalk_agent
    # 와 달리 부수효과 없는 순수 진단 노드라 굳이 그래프 레벨 재시도가 필요 없음).
    builder.add_node("fallback_orchestrator", fallback_orchestrator_node)

    # 신규·미온보딩 유저는 세션을 여는 순간 딸랑구가 먼저 자기소개와 이름
    # 질문(또는 이미 이름을 안다면 그 이름으로 바로 인사)을 건넨다. 기존/
    # 온보딩완료 유저는 그대로 wait_for_input에서 사용자 입력을 기다린다.
    builder.set_entry_point("session_start")
    builder.add_conditional_edges(
        "session_start",
        route_session_start,
        {"smalltalk_agent": "smalltalk_agent", "wait_for_input": "wait_for_input"},
    )
    builder.add_edge("wait_for_input", "reset_turn_observability")
    # 온보딩 미완료 신규유저는 intent_agent를 거치지 않고 바로 smalltalk_agent로
    # (route_entry, src/graph/router.py 참고) — smalltalk는 LLM이 매턴 판단하는
    # intent가 아니라 코드가 결정하는 온보딩 이벤트다.
    builder.add_conditional_edges(
        "reset_turn_observability",
        route_entry,
        {"smalltalk_agent": "smalltalk_agent", "intent_agent": "intent_agent"},
    )

    builder.add_conditional_edges("intent_agent", route, _ROUTE_DESTINATIONS)

    # after_fallback_orchestrator: action="clarify"/"chat"이면 respond로, action=
    # "recover"면 route()를 그대로 재호출한 결과이므로 route()가 갈 수 있는 곳은
    # 어디든 갈 수 있다 — 그래서 intent_agent와 같은 목적지 집합을 공유한다.
    builder.add_conditional_edges("fallback_orchestrator", after_fallback_orchestrator, _ROUTE_DESTINATIONS)

    builder.add_conditional_edges(
        "context_agent",
        after_context_agent,
        {"product_agent": "product_agent", "respond": "respond"},
    )

    builder.add_conditional_edges(
        "reorder_agent",
        after_reorder_agent,
        {"respond": "respond", "product_agent": "product_agent"},
    )

    builder.add_edge("ask_what_to_buy", "respond")

    builder.add_conditional_edges(
        "product_agent",
        after_product_agent,
        {"response_agent": "response_agent", "respond": "respond"},
    )
    builder.add_conditional_edges(
        "response_agent",
        after_response_agent,
        {"respond": "respond"},
    )

    builder.add_conditional_edges(
        "recipe_agent",
        after_recipe_agent,
        {"context_agent": "context_agent", "respond": "respond"},
    )

    builder.add_conditional_edges(
        "payment_agent",
        after_payment_agent,
        {"context_agent": "context_agent", "recipe_agent": "recipe_agent", "respond": "respond"},
    )
    builder.add_edge("cancel", "respond")
    builder.add_edge("smalltalk_agent", "respond")

    builder.add_conditional_edges(
        "respond",
        after_respond,
        {"wait_for_input": "wait_for_input", "end": END},
    )

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["wait_for_input"],
    )


def create_default_graph():
    return build_graph()
