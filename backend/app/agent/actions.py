"""
confirm_action 변환.

프론트가 버튼 탭으로 보내는 action (accept / reject / continue_shopping / checkout_cart / ...)을
LangGraph state patch로 변환해 inject_and_resume에 넘긴다.

흐름:
  1. 추천 상품 → 프론트: accept / reject
  2. accept → payment_agent Step 0: 장바구니 담기 + "계속 쇼핑?" pending
  3. 프론트: continue_shopping / checkout_cart
  4. checkout_cart → payment_agent Step 1: 결제수단 → 배송지 → 비밀번호 → 완료
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

    if action in ("accept", "order_now", "add_to_cart"):
        # 추천 상품 수락 → payment_agent Step 0에서 장바구니 담기 + "계속 쇼핑?" 처리
        return {
            "intent": "confirm",
            "pending_action": None,
            "messages": [HumanMessage(content="주문할게요")],
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
