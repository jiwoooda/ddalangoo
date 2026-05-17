"""
LangGraph 실행 wrapper.

그래프는 interrupt_before=["wait_for_input"] 로 컴파일되어 있어,
매 사용자 입력마다 아래 패턴으로 동작한다.

  [최초]
  1. invoke(초기 state, config)  → wait_for_input 직전에서 interrupt
  2. update_state(config, {messages: [user_msg]})
  3. invoke(None, config)        → 그래프 실행 → 다음 wait_for_input 직전에서 interrupt

  [이후 메시지]
  1. update_state(config, {messages: [user_msg]})
  2. invoke(None, config)        → 실행 → interrupt

thread_id = conversation_id 로 사용한다.
"""

import sys
import os
import uuid
from dotenv import load_dotenv

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

# vendor 경로를 Python path에 추가
_VENDOR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../vendor/ddalangoo-langgraph")
)
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from langchain_core.messages import HumanMessage
from src.graph.builder import build_graph
from src.state.schema import get_default_shopping_state

# 그래프 싱글턴 (서버 시작 시 한 번만 빌드)
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _config(conversation_id: int) -> dict:
    return {"configurable": {"thread_id": str(conversation_id)}}


def update_state(conversation_id: int, patch: dict) -> dict:
    """
    외부 sync 단계에서 생성한 값을 LangGraph checkpoint에 반영한다.
    예) recommendation_item_id를 state 상품 후보/pending_action에 주입.
    """
    graph = get_graph()
    config = _config(conversation_id)
    graph.update_state(config, patch)
    return graph.get_state(config).values


def start(user_id: int, message: str, conversation_id: int) -> dict:
    """
    새 대화 시작. 그래프를 초기화하고 첫 메시지를 처리한다.
    Returns: 최종 ShoppingState dict
    """
    graph = get_graph()
    config = _config(conversation_id)

    initial_state = get_default_shopping_state(
        user_id=str(user_id),
        session_id=str(uuid.uuid4()),
    )
    initial_state["conversation_id"] = conversation_id

    # 1. 초기 invoke → wait_for_input 직전 interrupt
    graph.invoke(initial_state, config)

    # 2. 사용자 메시지 주입
    graph.update_state(config, {"messages": [HumanMessage(content=message)]})

    # 3. 재개 → 그래프 실행 → 다음 interrupt
    graph.invoke(None, config)

    return graph.get_state(config).values


def resume(conversation_id: int, message: str) -> dict:
    """
    기존 대화에 메시지를 추가하고 그래프를 재개한다.
    Returns: 최종 ShoppingState dict
    """
    graph = get_graph()
    config = _config(conversation_id)

    graph.update_state(config, {"messages": [HumanMessage(content=message)]})
    graph.invoke(None, config)

    return graph.get_state(config).values


def inject_and_resume(conversation_id: int, patch: dict) -> dict:
    """
    confirm_action 등 프론트가 직접 state 변경을 주입할 때 사용.
    예) {"intent": "confirm", "messages": [HumanMessage(content="확인")]}
    Returns: 최종 ShoppingState dict
    """
    graph = get_graph()
    config = _config(conversation_id)

    graph.update_state(config, patch)
    graph.invoke(None, config)

    return graph.get_state(config).values
