"""
공통 Graph 노드: wait_for_input, respond, interrupt_payment.
"""
from src.state.schema import ShoppingState
from src.utils.agent_logger import agent_logger


def wait_for_input_node(state: ShoppingState) -> dict:
    """
    사용자 입력 대기 노드.
    interrupt_before=["wait_for_input"] 설정으로 이 지점에서 항상 멈춘다.
    실제 실행 시 이 함수는 거의 실행되지 않는다.
    """
    return {}


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

    agent_logger.log_respond(msg, stage, pending_action)
    return {
        "messages": [{"role": "assistant", "content": msg}]
    }


def quantity_check_node(state: ShoppingState) -> dict:
    """
    상품 확인 후 수량이 없을 때 호출.
    pending_action으로 수량 질문을 설정하고 respond로 넘긴다.
    """
    keywords = state.get("keywords") or []
    short_name = keywords[0] if keywords else (state.get("selected_product") or {}).get("product_name", "상품")
    return {
        "pending_action": {
            "type": "quantity_confirm",
            "message": f"{short_name} 몇 개 사실래요?",
        }
    }


def ask_what_to_buy_node(state: ShoppingState) -> dict:
    """
    장바구니 담은 후 '다른것도 살래' 등 추가 쇼핑 의사 표현 시 호출.
    cart session(storage_state_path)은 보존하고 새 상품 입력을 기다린다.
    """
    return {
        "pending_action": {
            "type": "what_to_buy",
            "message": "무엇을 구매하실까요?",
        },
        "stage": "cart_shopping",
        "keywords": [],
        "search_results": [],
        "selected_product": None,
        "reorder_resolution": None,
        "error": None,
        "quantity": None,
        "product_url": None,
        "current_product_index": 0,
        "explanation": None,
        "highlight_specs": [],
        "scored_products": [],
        "recommended_products": [],
    }


def cancel_node(state: ShoppingState) -> dict:
    """
    모든 stage에서의 cancel 처리.
    - 장바구니 항목 있으면: 담아둔 것 유지 안내
    - 없으면: 단순 취소 안내
    state 완전 리셋 (cart_items·storage_state_path 제외).
    """
    cart_items = state.get("cart_items") or []
    if cart_items:
        msg = "알겠어요~ 처음으로 돌아갈게요! 장바구니에 담아둔 건 그대로 있을 거에요 :)"
    else:
        msg = "알겠어요~ 필요하면 언제든 말씀해주세요!"

    return {
        "stage": "idle",
        "intent": None,
        "error": None,
        "pending_action": {"type": "payment_confirm", "message": msg},
        "last_agent": "cancel",
        "keywords": [],
        "search_results": [],
        "scored_products": [],
        "recommended_products": [],
        "selected_product": None,
        "product_url": None,
        "explanation": None,
        "highlight_specs": [],
        "current_product_index": 0,
        "quantity": None,
        "reorder_resolution": None,
    }
