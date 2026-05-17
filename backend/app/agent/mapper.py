"""
ShoppingState → AgentResponse 변환.

LangGraph ShoppingState의 필드를 기존 FastAPI AgentResponse 스키마로 매핑한다.
프론트 계약(AgentResponse)을 유지하면서 백엔드 구현만 교체하는 것이 목적이다.
"""

from typing import Optional
from app.schemas.agent import AgentResponse, RecommendationItemInAgent


def _recommendation_item_id(product: dict) -> int | None:
    return (
        product.get("recommendation_item_id")
        or product.get("recommendationItemId")
    )


def _map_product(p: dict) -> RecommendationItemInAgent:
    """ShoppingState의 recommended_products 항목 → RecommendationItemInAgent"""
    return RecommendationItemInAgent(
        recommendationItemId=_recommendation_item_id(p),
        productId=p.get("product_id", 0),
        productName=p.get("product_name") or p.get("name", ""),
        brand=p.get("brand"),
        price=p.get("price", 0),
        rank=p.get("rank", 0),
        optionText=p.get("option_text"),
        deliveryInfo=p.get("delivery_info"),
        deliveryFee=p.get("delivery_fee"),
        rating=p.get("rating"),
        reviewCount=p.get("review_count"),
        imageUrl=p.get("image_url"),
        productUrl=p.get("product_url") or p.get("url"),
        platform=p.get("platform"),
        reason=p.get("reason") or p.get("explanation"),
        isSelected=p.get("is_selected", False),
        isOrderable=p.get("is_orderable", True),
        orderBlockReason=p.get("order_block_reason"),
    )


def _candidate_products(state: dict) -> list[dict]:
    recommended = state.get("recommended_products") or []
    search_results = state.get("search_results") or []
    return recommended or search_results


def _map_pending(pending_action: Optional[dict]) -> Optional[dict]:
    """
    ShoppingState.pending_action → AgentResponse.pendingConfirmation

    pending_action.type 기준으로 프론트가 기대하는 형태로 변환한다.
    """
    if not pending_action:
        return None

    ptype = pending_action.get("type")
    payload = pending_action.get("payload") or {}
    message = pending_action.get("message", "")

    if ptype == "product_confirm":
        mapped_payload = {
            "actions": payload.get("actions", ["order_now", "add_to_cart", "reject"]),
        }
        item_id = payload.get("recommendationItemId") or payload.get("recommendation_item_id")
        if item_id:
            mapped_payload["recommendationItemId"] = item_id
        return {
            "type": "product",
            "message": message,
            "payload": mapped_payload,
        }

    if ptype == "quantity_confirm":
        return {
            "type": "quantity",
            "message": message,
            "payload": payload,
        }

    if ptype == "clarification":
        return {"type": "clarification"}

    if ptype == "payment_confirm":
        return {
            "type": "payment",
            "message": message,
            "payload": payload,
        }

    if ptype == "address_confirm":
        return {
            "type": "address",
            "message": message,
            "payload": payload,
        }

    # 그 외 타입은 그대로 전달
    return {"type": ptype, "message": message, "payload": payload}


def _last_assistant_message(state: dict) -> str:
    """messages 리스트에서 마지막 assistant 메시지를 꺼낸다."""
    messages = state.get("messages") or []
    for msg in reversed(messages):
        # LangGraph는 dict 또는 BaseMessage 객체 모두 가능
        role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else None)
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else "")
        if role in ("ai", "assistant"):
            return content
    return "무엇을 도와드릴까요?"


def _stage_to_status(stage: str) -> str:
    """ShoppingState.stage → AgentResponse.status"""
    mapping = {
        "idle": "intent_detected",
        "searching": "searching",
        "product_confirming": "waiting_user_confirmation",
        "cart_shopping": "waiting_user_confirmation",
        "payment_processing": "payment_processing",
        "completed": "order_completed",
        "failed": "failed",
    }
    return mapping.get(stage, "intent_detected")


def state_to_response(state: dict, conversation_id: int) -> AgentResponse:
    """
    ShoppingState dict → AgentResponse

    AgentResponse 스키마를 유지하면서 LangGraph 결과를 프론트에 전달한다.
    """
    stage = state.get("stage", "idle")
    candidates = _candidate_products(state)

    return AgentResponse(
        conversationId=conversation_id,
        status=_stage_to_status(stage),
        stage=stage,
        assistantMessage=_last_assistant_message(state),
        recommendationId=None,  # LangGraph는 recommendation ID를 별도 관리하지 않음
        recommendations=[_map_product(p) for p in candidates[:2]],
        selectedProduct=state.get("selected_product"),
        pendingConfirmation=_map_pending(state.get("pending_action")),
        availableOptions=None,
        deliveryAddress=None,
        order=None,
        payment=None,
        uiCommand=None,
        asyncStatus=None,
        error=state.get("error"),
    )
