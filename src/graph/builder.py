"""
Orchestrator Graph Builder.

LangGraph StateGraph 구성:
- wait_for_input → intent_agent → route() → {agents} → respond → after_respond()
- interrupt_before=["wait_for_input"] (human-in-the-loop)
- MemorySaver / InMemoryStore (baseline; production: PostgresSaver/PostgresStore)
"""
from typing import Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.store.base import BaseStore

from src.state.schema import ShoppingState
from src.graph.router import route, after_respond, after_reorder
from src.agents.intent_agent import intent_agent_node
from src.agents.memory_agent import memory_agent_node
from src.agents.platform_agent import platform_agent_node
from src.agents.product_agent import product_agent_node
from src.agents.reorder_node import reorder_node
from src.agents.nodes import wait_for_input_node, respond_node, interrupt_payment_node
from src.payment.subgraph import payment_agent_node


def build_graph(
    checkpointer=None,
    store: Optional[BaseStore] = None,
):
    """
    LangGraph Orchestrator Graph 구성.

    Parameters
    ----------
    checkpointer : 체크포인터 (기본: MemorySaver)
    store : KV 스토어 (기본: InMemoryStore)

    Returns
    -------
    CompiledGraph
    """
    if checkpointer is None:
        checkpointer = MemorySaver()
    if store is None:
        store = InMemoryStore()

    # ── Store-aware memory 클로저 (store는 장기 이력 보존 목적) ──
    def _memory_agent_node(state: ShoppingState) -> dict:
        return memory_agent_node(state, store=store)

    # ── Graph 구성 ──
    builder = StateGraph(ShoppingState)

    # ── 노드 등록 ──
    builder.add_node("wait_for_input", wait_for_input_node)
    builder.add_node("intent_agent", intent_agent_node)
    builder.add_node("memory_agent", _memory_agent_node)
    builder.add_node("reorder_node", reorder_node)
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

    # ── memory_agent → reorder_node (항상) ──
    builder.add_edge("memory_agent", "reorder_node")

    # ── reorder_node → respond (URL 유효) / platform_agent (URL 실패 fallback) ──
    builder.add_conditional_edges(
        "reorder_node",
        after_reorder,
        {
            "respond": "respond",
            "platform_agent": "platform_agent",
        },
    )

    # ── 각 Agent 이후 응답 생성 ──
    builder.add_edge("platform_agent", "respond")
    builder.add_edge("product_agent", "respond")
    builder.add_edge("payment_agent", "respond")
    builder.add_edge("interrupt_payment", "respond")

    # ── respond 이후 계속 진행 여부 판단 ──
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


def create_default_graph():
    """기본 설정으로 그래프 생성 (테스트/개발용)."""
    return build_graph()
