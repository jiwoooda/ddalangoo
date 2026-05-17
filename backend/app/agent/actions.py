"""
confirm_action 변환.

프론트가 버튼 탭으로 보내는 action (order_now / add_to_cart / reject / ...)을
LangGraph state patch로 변환해 inject_and_resume에 넘긴다.

LangGraph 라우터는 intent + stage 기준으로 동작하므로,
버튼 액션을 intent로 매핑하고 필요한 경우 pending_action도 함께 초기화한다.
"""

from langchain_core.messages import HumanMessage
from app.schemas.agent import ConfirmRequest


def resolve_recommendation_item_id(state: dict, req: ConfirmRequest) -> int | None:
    """
    현재 선택된 추천 후보 ID를 찾는다.

    Agent 중심 흐름에서는 state가 source of truth이므로 pending_action을 먼저 본다.
    """
    pending = state.get("pending_action") or {}
    payload = pending.get("payload") or {}
    selected = state.get("selected_product") or {}

    return (
        payload.get("recommendationItemId")
        or payload.get("recommendation_item_id")
        or selected.get("recommendation_item_id")
        or selected.get("recommendationItemId")
        or req.recommendationItemId
    )


def build_patch(req: ConfirmRequest) -> dict:
    """
    ConfirmRequest → ShoppingState patch dict

    Returns
    -------
    dict : inject_and_resume에 넘길 state patch
    """
    action = req.action

    if action == "order_now":
        # 상품 확인 → 결제 진행
        # router: stage=product_confirming + intent=confirm + quantity 없으면 quantity_check로 분기
        return {
            "intent": "confirm",
            "pending_action": None,
            "messages": [HumanMessage(content="주문할게요")],
        }

    if action == "add_to_cart":
        # 장바구니 담기 → cart_shopping stage로
        return {
            "intent": "confirm",
            "stage": "cart_shopping",
            "pending_action": {
                "type": "continue_shopping",
                "message": "장바구니에 담겼습니다. 계속 쇼핑하시겠어요, 아니면 바로 결제하시겠어요?",
                "payload": {"actions": ["continue_shopping", "checkout_cart"]},
            },
            "messages": [HumanMessage(content="장바구니에 담아줘")],
        }

    if action == "reject":
        # 다음 상품 보기
        return {
            "intent": "next",
            "pending_action": None,
            "messages": [HumanMessage(content="다른 거 보여줘")],
        }

    if action == "continue_shopping":
        return {
            "intent": "deny",
            "stage": "idle",
            "pending_action": None,
            "messages": [HumanMessage(content="계속 쇼핑할게요")],
        }

    if action == "checkout_cart":
        return {
            "intent": "confirm",
            "messages": [HumanMessage(content="결제할게요")],
        }

    if action == "cancel":
        return {
            "intent": "cancel",
            "messages": [HumanMessage(content="취소할게요")],
        }

    # 알 수 없는 action은 그대로 메시지로 전달
    return {
        "messages": [HumanMessage(content=action)],
    }
