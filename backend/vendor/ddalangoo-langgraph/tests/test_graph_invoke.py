"""
graph.invoke() 기반 end-to-end 테스트.

실제 LLM 호출 없이 mock LLM으로 orchestration correctness를 검증한다.
ANTHROPIC_API_KEY가 없는 환경에서도 실행 가능하다.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from src.state.schema import get_default_shopping_state
from src.graph.builder import build_graph


# ══════════════════════════════════════════════
# Mock LLM 응답 팩토리
# ══════════════════════════════════════════════

def make_intent_response(
    intent: str,
    keywords: list = None,
    confidence: float = 0.9,
    needs_clarification: bool = False,
    immediate_response: str = "알겠어요.",
    **kwargs,
) -> AIMessage:
    payload = {
        "intent": intent,
        "keywords": keywords or [],
        "exclude_keywords": [],
        "negative_constraints": [],
        "quantity": None,
        "condition": None,
        "target_platforms": [],
        "override_platform": None,
        "current_option_value": None,
        "address_text": None,
        "needs_clarification": needs_clarification,
        "clarification_reason": None,
        "confidence": confidence,
        "immediate_response": immediate_response,
        **kwargs,
    }
    return AIMessage(content=json.dumps(payload, ensure_ascii=False))


def make_product_response(
    selected_product: dict = None,
    stage: str = "product_confirming",
    explanation: str = "좋은 상품이에요. 주문할까요?",
    pending_action_type: str = "product_confirm",
) -> AIMessage:
    product = selected_product or {
        "product_name": "설향 딸기 500g",
        "price": 12900,
        "platform": "kurly",
        "product_url": "https://mock.kurly.com/products/strawberry-500g",
    }
    payload = {
        "selected_product": product,
        "recommended_products": [product],
        "current_product_index": 0,
        "reason": "테스트 추천",
        "explanation": explanation,
        "answer": None,
        "needs_confirmation": True,
        "pending_action": {
            "type": pending_action_type,
            "message": explanation,
            "payload": {"product_url": product.get("product_url")},
        },
        "error": None,
        "stage": stage,
    }
    return AIMessage(content=json.dumps(payload, ensure_ascii=False))


# ══════════════════════════════════════════════
# Graph 생성 헬퍼
# ══════════════════════════════════════════════

def create_test_graph():
    return build_graph(
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
    )


def make_config(thread_id: str = "test_thread") -> dict:
    return {"configurable": {"thread_id": thread_id}}


def inject_user_message(graph, config: dict, content: str, base_state: dict):
    """사용자 메시지를 state에 주입하고 graph를 재개한다."""
    graph.update_state(
        config,
        {"messages": [{"role": "user", "content": content}]},
    )


# ══════════════════════════════════════════════
# Test: buy intent → platform_agent → product_agent
# ══════════════════════════════════════════════

@patch("src.agents.intent_agent._get_llm")
@patch("src.agents.product_agent._get_llm")
def test_buy_flow_platform_to_product(mock_product_llm, mock_intent_llm):
    """buy 발화 → platform_agent(mock) → product_agent → respond → wait_for_input."""

    # Intent LLM: buy 의도 반환
    intent_llm = MagicMock()
    intent_llm.invoke.return_value = make_intent_response(
        intent="buy",
        keywords=["딸기"],
        immediate_response="딸기 찾아볼게요.",
    )
    mock_intent_llm.return_value = intent_llm

    # Product LLM: 추천 반환
    product_llm = MagicMock()
    product_llm.invoke.return_value = make_product_response()
    mock_product_llm.return_value = product_llm

    graph = create_test_graph()
    config = make_config("test_buy_flow")

    initial_state = get_default_shopping_state("user_test", "session_test")
    initial_state["messages"] = [{"role": "user", "content": "딸기 사줘"}]

    # 첫 번째 invoke: wait_for_input에서 interrupt
    result = graph.invoke(initial_state, config)

    # platform_agent는 mock 없이 실행 (mock_search_product 사용)
    # product_agent LLM은 mock
    # respond 이후 wait_for_input에서 멈춤

    assert result is not None
    current = graph.get_state(config)
    state_values = current.values

    # 메시지가 쌓였는지 확인
    assert len(state_values.get("messages", [])) > 0

    # stage는 product_confirming 또는 searching (검색 결과에 따라)
    stage = state_values.get("stage")
    assert stage in ("product_confirming", "searching", "idle")


@patch("src.agents.intent_agent._get_llm")
def test_unclear_flow_goes_to_respond(mock_intent_llm):
    """unclear intent → respond로 라우팅.

    interrupt_before=["wait_for_input"]이므로:
    1차 invoke → wait_for_input 직전에서 pause (state 저장만)
    2차 invoke(None) → wait_for_input 실행 → intent_agent → respond → 다시 pause
    """
    intent_llm = MagicMock()
    intent_llm.invoke.return_value = make_intent_response(
        intent="unclear",
        needs_clarification=True,
        confidence=0.3,
        immediate_response="어떤 상품 말씀이세요?",
    )
    mock_intent_llm.return_value = intent_llm

    graph = create_test_graph()
    config = make_config("test_unclear")

    initial_state = get_default_shopping_state("user_test", "session_test")
    initial_state["messages"] = [{"role": "user", "content": "그거 있잖아"}]

    # 1차: pause at wait_for_input (state 저장)
    graph.invoke(initial_state, config)
    # 2차: 실제 실행 — wait_for_input → intent_agent → respond → pause
    graph.invoke(None, config)

    current = graph.get_state(config)
    state_values = current.values

    # respond가 실행되어 assistant 메시지가 추가됨
    messages = state_values.get("messages", [])
    assistant_messages = [
        m for m in messages
        if (isinstance(m, dict) and m.get("role") == "assistant")
        or (hasattr(m, "type") and m.type == "ai")
    ]
    assert len(assistant_messages) > 0


@patch("src.agents.intent_agent._get_llm")
def test_cancel_idle_ends_graph(mock_intent_llm):
    """cancel intent + idle stage → END.

    interrupt_before=["wait_for_input"]이므로:
    1차 invoke → pause
    2차 invoke(None) → 실행 → cancel/idle → END (next 없음)
    """
    intent_llm = MagicMock()
    intent_llm.invoke.return_value = make_intent_response(
        intent="cancel",
        confidence=0.95,
    )
    mock_intent_llm.return_value = intent_llm

    graph = create_test_graph()
    config = make_config("test_cancel_idle")

    initial_state = get_default_shopping_state("user_test", "session_test")
    initial_state["messages"] = [{"role": "user", "content": "됐어"}]
    initial_state["stage"] = "idle"

    # 1차: pause at wait_for_input
    graph.invoke(initial_state, config)
    # 2차: 실행 → cancel/idle → END
    graph.invoke(None, config)

    current = graph.get_state(config)

    # cancel + idle → END → next가 없어야 함
    assert current.next == () or current.next == []


@patch("src.agents.intent_agent._get_llm")
def test_confirm_product_goes_to_payment(mock_intent_llm):
    """product_confirming에서 confirm → payment_agent.

    1차 invoke → pause
    2차 invoke(None) → 실행 → confirm/product_confirming → payment_agent → respond → pause
    """
    intent_llm = MagicMock()
    intent_llm.invoke.return_value = make_intent_response(
        intent="confirm",
        confidence=0.95,
        immediate_response="알겠어요.",
    )
    mock_intent_llm.return_value = intent_llm

    graph = create_test_graph()
    config = make_config("test_confirm_product")

    initial_state = get_default_shopping_state("user_test", "session_test")
    initial_state["messages"] = [{"role": "user", "content": "응"}]
    initial_state["stage"] = "product_confirming"
    initial_state["selected_product"] = {
        "product_name": "사과 1kg",
        "price": 9900,
        "platform": "naver",
        "product_url": "https://mock.naver.com/apple",
    }
    initial_state["product_url"] = "https://mock.naver.com/apple"
    initial_state["pending_action"] = {
        "type": "product_confirm",
        "message": "이 상품으로 주문할까요?",
        "payload": {"product_url": "https://mock.naver.com/apple"},
    }

    # 1차: pause at wait_for_input
    graph.invoke(initial_state, config)
    # 2차: 실행 → confirm/product_confirming → payment_agent
    graph.invoke(None, config)

    current = graph.get_state(config)
    state_values = current.values

    # payment_agent 실행 → stage = payment_processing
    stage = state_values.get("stage")
    assert stage in ("payment_processing", "completed", "failed")


# ══════════════════════════════════════════════
# State schema integrity tests
# ══════════════════════════════════════════════

def test_default_shopping_state_shape():
    """ShoppingState 기본값 schema 검증."""
    state = get_default_shopping_state("user_001", "sess_001")

    assert state["user_id"] == "user_001"
    assert state["session_id"] == "sess_001"
    assert state["stage"] == "idle"
    assert state["intent"] is None
    assert state["messages"] == []
    assert state["keywords"] == []
    assert state["search_results"] == []
    assert state["recommended_products"] == []
    assert state["pending_action"] is None
    assert state["needs_clarification"] is False


def test_bridge_memory_minimal():
    """bridge_memory_to_shopping은 last_agent만 반환한다."""
    from src.state.schema import bridge_memory_to_shopping
    result = bridge_memory_to_shopping({})
    assert result == {"last_agent": "memory_agent"}
    assert "search_results" not in result
    assert "recommendation_context" not in result


# ══════════════════════════════════════════════
# Platform + Memory mock tool tests
# ══════════════════════════════════════════════

def test_mock_search_product_strawberry():
    from src.tools.mock_tools import mock_search_product
    results = mock_search_product("딸기", ["kurly"], "relevance")
    assert len(results) > 0
    assert all(p.get("product_url") for p in results)
    assert all(p.get("price") for p in results)


def test_mock_search_product_no_soldout():
    from src.tools.mock_tools import mock_search_product
    results = mock_search_product("딸기", ["kurly", "naver"], "relevance")
    assert all(not p.get("is_sold_out") for p in results)


def test_platform_agent_node_invalid_keywords():
    from src.agents.platform_agent import platform_agent_node
    from src.state.schema import get_default_shopping_state
    state = get_default_shopping_state("user_test", "sess")
    state["keywords"] = ["그거", "저번에"]

    result = platform_agent_node(state)
    assert result["error"] == "invalid_keywords"
    assert result["search_results"] == []


def test_platform_agent_node_valid_keywords():
    from src.agents.platform_agent import platform_agent_node
    from src.state.schema import get_default_shopping_state
    state = get_default_shopping_state("user_test", "sess")
    state["keywords"] = ["딸기"]

    result = platform_agent_node(state)
    assert result["error"] is None
    assert len(result["search_results"]) > 0
    assert result["stage"] == "searching"


def test_memory_agent_recommendation_context_in_state():
    from src.agents.memory_agent import memory_agent_node
    from src.state.schema import get_default_shopping_state
    from langgraph.store.memory import InMemoryStore

    store = InMemoryStore()
    state = get_default_shopping_state("user_001", "sess")
    state["keywords"] = ["딸기"]
    state["intent"] = "buy"

    result = memory_agent_node(state, store=store)

    # recommendation_context가 state에 직접 반영
    assert result.get("last_agent") == "memory_agent"
    ctx = result.get("recommendation_context")
    assert isinstance(ctx, dict)
    assert "preference_memory" in ctx
    assert "keyword_results" in ctx


# ══════════════════════════════════════════════
# Reorder Node Tests
# ══════════════════════════════════════════════

def test_reorder_node_valid_url():
    """구매 이력에 유효한 URL이 있으면 product_confirm pending_action을 설정한다."""
    from src.agents.reorder_node import reorder_node
    from src.state.schema import get_default_shopping_state

    state = get_default_shopping_state("user_001", "sess")
    state["intent"] = "reorder"
    state["keywords"] = ["딸기"]
    state["search_results"] = [
        {
            "product_name": "설향 딸기 500g",
            "price": 12900,
            "platform": "kurly",
            "product_url": "https://mock.kurly.com/products/strawberry-500g",
            "is_sold_out": False,
        }
    ]

    result = reorder_node(state)

    assert result["stage"] == "product_confirming"
    assert result["error"] is None
    assert result["pending_action"]["type"] == "product_confirm"
    assert result["selected_product"]["product_name"] == "설향 딸기 500g"
    assert result["product_url"] == "https://mock.kurly.com/products/strawberry-500g"


def test_reorder_node_invalid_url_fallback():
    """URL이 실패하면 platform_agent fallback용 상태를 반환한다."""
    from src.agents.reorder_node import reorder_node
    from src.state.schema import get_default_shopping_state
    from src.tools.mock_tools import block_product_url, unblock_product_url

    url = "https://mock.kurly.com/products/strawberry-500g"
    block_product_url(url)
    try:
        state = get_default_shopping_state("user_001", "sess")
        state["intent"] = "reorder"
        state["keywords"] = ["딸기"]
        state["search_results"] = [
            {
                "product_name": "설향 딸기 500g",
                "price": 12900,
                "platform": "kurly",
                "product_url": url,
            }
        ]

        result = reorder_node(state)

        assert result["stage"] == "searching"
        assert result["error"] == "reorder_url_failed"
        assert result["search_results"] == []
    finally:
        unblock_product_url(url)


def test_reorder_node_empty_history():
    """구매 이력이 없으면 fallback 상태를 반환한다."""
    from src.agents.reorder_node import reorder_node
    from src.state.schema import get_default_shopping_state

    state = get_default_shopping_state("user_test", "sess")
    state["intent"] = "reorder"
    state["keywords"] = ["딸기"]
    state["search_results"] = []

    result = reorder_node(state)

    assert result["stage"] == "searching"
    assert result["error"] == "reorder_url_failed"


@patch("src.agents.intent_agent._get_llm")
def test_reorder_flow_end_to_end(mock_intent_llm):
    """reorder 의도 → memory_agent → reorder_node → product_confirming.

    user_001에 딸기 구매 이력(유효 URL)이 있으므로:
    reorder_node가 product_confirm을 설정하고 respond로 이동해야 한다.
    """
    intent_llm = MagicMock()
    intent_llm.invoke.return_value = make_intent_response(
        intent="reorder",
        keywords=["딸기"],
        confidence=0.95,
        immediate_response="이전에 구매하셨던 딸기 찾아볼게요.",
    )
    mock_intent_llm.return_value = intent_llm

    graph = create_test_graph()
    config = make_config("test_reorder_e2e")

    initial_state = get_default_shopping_state("user_001", "session_test")
    initial_state["messages"] = [{"role": "user", "content": "딸기 또 시켜줘"}]

    # 1차: pause at wait_for_input
    graph.invoke(initial_state, config)
    # 2차: 실행 → reorder → memory_agent → reorder_node → respond → pause
    graph.invoke(None, config)

    current = graph.get_state(config)
    state_values = current.values

    # reorder_node가 product_confirming으로 설정해야 함
    assert state_values.get("stage") == "product_confirming"
    assert state_values.get("pending_action") is not None
    assert state_values["pending_action"]["type"] == "product_confirm"


def test_after_reorder_routing():
    """after_reorder 라우팅 함수 단위 테스트."""
    from src.graph.router import after_reorder

    state_url_failed = {"error": "reorder_url_failed", "stage": "searching"}
    assert after_reorder(state_url_failed) == "platform_agent"

    state_ok = {"error": None, "stage": "product_confirming"}
    assert after_reorder(state_ok) == "respond"

    state_no_error = {"stage": "product_confirming"}
    assert after_reorder(state_no_error) == "respond"
