"""
ShoppingState -> AgentResponse 변환.

LangGraph ShoppingState의 내부 필드를 프론트 API 명세의 AgentResponse로 매핑한다.
프론트 계약은 유지하고, 백엔드 내부 구현만 LangGraph로 교체하는 것이 목적이다.
"""

from typing import Any, Optional
from app.schemas.agent import AgentResponse, RecommendationItemInAgent
from app.services import webview_progress_service


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


def _payload_with_subtype(payload: dict, subtype: str) -> dict:
    """프론트 type은 크게 유지하고, LangGraph 내부 세부 타입은 payload.subType에 보존한다."""
    mapped_payload = dict(payload)
    mapped_payload.setdefault("subType", subtype)
    return mapped_payload


def _product_confirm_actions(payload: dict) -> list[str]:
    """내부 accept 표현을 프론트 계약의 order_now 표현으로 정규화한다."""
    actions = payload.get("actions") or ["order_now", "add_to_cart", "reject"]
    normalized: list[str] = []
    for action in actions:
        mapped_action = "order_now" if action == "accept" else action
        if mapped_action not in normalized:
            normalized.append(mapped_action)

    if payload.get("orderBlockReason"):
        return normalized

    documented_order = ["order_now", "add_to_cart", "reject"]
    for required_action in documented_order:
        if required_action not in normalized:
            normalized.append(required_action)

    ordered_actions = [action for action in documented_order if action in normalized]
    extra_actions = [action for action in normalized if action not in documented_order]
    return ordered_actions + extra_actions


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
            "actions": _product_confirm_actions(payload),
        }
        item_id = payload.get("recommendationItemId") or payload.get("recommendation_item_id")
        if item_id:
            mapped_payload["recommendationItemId"] = item_id
        if payload.get("orderBlockReason"):
            mapped_payload["orderBlockReason"] = payload["orderBlockReason"]
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

    if ptype == "price_change_confirm":
        return {
            "type": "price_changed",
            "message": message,
            "payload": _payload_with_subtype(payload, "price_change_confirm"),
        }

    if ptype == "clarification":
        return {
            "type": "clarification",
            "message": message,
            "payload": payload or None,
        }

    if ptype == "payment_method_confirm":
        return {
            "type": "payment",
            "message": message,
            "payload": _payload_with_subtype(payload, "payment_method_confirm"),
        }

    if ptype == "payment_password":
        return {
            "type": "payment",
            "message": message,
            "payload": _payload_with_subtype(payload, "payment_password"),
        }

    if ptype == "payment_confirm":
        return {
            "type": "payment",
            "message": message,
            "payload": _payload_with_subtype(payload, "payment_confirm"),
        }

    if ptype == "address_confirm":
        return {
            "type": "address",
            "message": message,
            "payload": payload,
        }

    if ptype == "address_required":
        return {
            "type": "address",
            "message": message,
            "payload": _payload_with_subtype(payload, "address_required"),
        }

    if ptype == "platform_suggest":
        return {
            "type": "clarification",
            "message": message,
            "payload": _payload_with_subtype(payload, "platform_suggest"),
        }

    if ptype == "webview_task":
        return {
            "type": "webview_task",
            "message": message,
            "payload": payload,
        }

    if ptype == "continue_shopping":
        return {
            "type": "payment",
            "message": message,
            "payload": _payload_with_subtype(payload, "continue_shopping"),
        }

    # 새 LangGraph pending 타입이 생겨도 프론트의 큰 흐름은 깨지지 않도록 clarification으로 감싼다.
    return {
        "type": "clarification",
        "message": message,
        "payload": _payload_with_subtype(payload, ptype or "unknown"),
    }


def _last_assistant_message(state: dict) -> str:
    """messages 리스트에서 마지막 assistant 메시지를 꺼낸다."""
    messages = state.get("messages") or []
    for msg in reversed(messages):
        # LangGraph는 dict 또는 BaseMessage 객체 모두 가능
        role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else None)
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else "")
        if role in ("ai", "assistant"):
            return content

    pending_action = state.get("pending_action") or {}
    pending_message = pending_action.get("message")
    if isinstance(pending_message, str) and pending_message.strip():
        return pending_message.strip()

    if state.get("needs_clarification") or state.get("intent") == "unclear":
        return (
            state.get("clarification_reason")
            or state.get("immediate_response")
            or "잘 못 들었어요. 구매하고 싶은 상품 이름을 다시 말씀해주세요."
        )

    return "무엇을 도와드릴까요?"


def _stage_to_status(stage: str) -> str:
    """API 명세 기준 stage -> status 변환."""
    mapping = {
        "idle": "started",
        "searching": "searching_product",
        "product_confirming": "waiting_user_confirmation",
        "address_confirming": "waiting_user_confirmation",
        "address_required": "address_required",
        "cart_shopping": "waiting_user_confirmation",
        "webview_cart": "cart_processing",
        "cart_processing": "cart_processing",
        "payment_precheck": "payment_in_progress",
        "payment_password_required": "payment_in_progress",
        "payment_processing": "payment_in_progress",
        "completed": "order_completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    return mapping.get(stage, "started")


def _payment_url_from(value: Any) -> Optional[str]:
    """state/payload 안에서 프론트 웹뷰로 열 수 있는 결제 URL을 찾는다."""
    if not isinstance(value, dict):
        return None
    return (
        value.get("paymentUrl")
        or value.get("payment_url")
        or value.get("url")
    )


def _map_ui_command(state: dict) -> Optional[dict]:
    """
    LangGraph가 웹뷰 명령이나 결제 URL을 만든 경우에만 uiCommand를 내려준다.

    현재 LangGraph MVP 결제는 fake password 방식이라 결제 URL이 없을 수 있다.
    mapper가 없는 URL을 만들어내면 프론트가 실제 결제창을 열 수 없으므로, URL이 있을 때만 변환한다.
    """
    direct_command = state.get("uiCommand") or state.get("ui_command")
    if isinstance(direct_command, dict):
        return direct_command

    pending_action = state.get("pending_action") or {}
    pending_payload = pending_action.get("payload") or {}
    payload_command = pending_payload.get("uiCommand") or pending_payload.get("ui_command")
    if isinstance(payload_command, dict):
        return payload_command

    payment_url = (
        _payment_url_from(state)
        or _payment_url_from(pending_payload)
        or _payment_url_from(state.get("payment") or {})
    )
    if payment_url:
        return {
            "type": "open_webview",
            "target": "payment",
            "url": payment_url,
        }

    return None


def _map_stage(state: dict, ui_command: Optional[dict]) -> str:
    """
    LangGraph 내부 stage를 프론트 명세 stage로 보정한다.

    LangGraph는 결제 세부 단계를 pending_action.type으로 표현하는 경우가 있어서,
    프론트가 화면을 바꾸기 쉬운 stage로 한 번 더 번역한다.
    """
    stage = state.get("stage", "idle")
    pending_type = (state.get("pending_action") or {}).get("type")

    if pending_type == "address_confirm":
        return "address_confirming"

    if pending_type == "address_required":
        return "address_required"

    if pending_type == "payment_method_confirm":
        return "payment_precheck"

    if pending_type == "price_change_confirm":
        return "payment_precheck"

    if (
        pending_type == "payment_password"
        and isinstance(ui_command, dict)
        and ui_command.get("type") == "open_webview"
    ):
        return "payment_password_required"

    return stage


def state_to_response(state: dict, conversation_id: int) -> AgentResponse:
    """
    ShoppingState dict → AgentResponse

    AgentResponse 스키마를 유지하면서 LangGraph 결과를 프론트에 전달한다.
    """
    ui_command = _map_ui_command(state)
    stage = _map_stage(state, ui_command)
    candidates = _candidate_products(state)
    async_status = (
        state.get("asyncStatus")
        or state.get("async_status")
        or state.get("webview_progress")
        or webview_progress_service.get_latest_status(conversation_id)
    )

    return AgentResponse(
        conversationId=conversation_id,
        status=_stage_to_status(stage),
        stage=stage,
        assistantMessage=_last_assistant_message(state),
        message=_last_assistant_message(state),
        recommendationId=state.get("recommendation_id") or state.get("recommendationId"),
        recommendations=[_map_product(p) for p in candidates[:2]],
        selectedProduct=state.get("selected_product"),
        pendingConfirmation=_map_pending(state.get("pending_action")),
        availableOptions=state.get("available_options") or state.get("availableOptions"),
        deliveryAddress=state.get("delivery_address") or state.get("deliveryAddress"),
        cart=state.get("cart"),
        order=state.get("order"),
        payment=state.get("payment"),
        uiCommand=ui_command,
        asyncStatus=async_status,
        error=state.get("error"),
    )
