from app.repositories import (
    conversation_repository, recommendation_repository,
    address_repository, user_repository, purchase_history_repository
)
from app.schemas.agent import AgentResponse, ShoppingRequest, MessageRequest, ConfirmRequest, RecommendationItemInAgent
from fastapi import HTTPException

KEYWORD_MAP = {"딸기": "strawberry", "참기름": "sesame_oil", "두유": "soy_milk"}
CONFIRM_MESSAGES = {"확인", "응", "그래", "맞아", "좋아"}

def _detect_keyword(message: str) -> str:
    for kor, eng in KEYWORD_MAP.items():
        if kor in message:
            return eng
    return "clarification"

def _to_agent_item(i: dict) -> RecommendationItemInAgent:
    return RecommendationItemInAgent(
        recommendationItemId=i["id"], productId=i["product_id"], productName=i["product_name"],
        brand=i.get("brand"), price=i["price"], rank=i["rank"], optionText=i.get("option_text"),
        deliveryInfo=i.get("delivery_info"), deliveryFee=i.get("delivery_fee"),
        rating=i.get("rating"), reviewCount=i.get("review_count"), imageUrl=i.get("image_url"),
        productUrl=i.get("product_url"), platform=i.get("platform"), reason=i.get("reason"),
        isSelected=i.get("is_selected", False), isOrderable=i["is_orderable"],
        orderBlockReason=i.get("order_block_reason")
    )

def _get_rec_items(keyword: str):
    rec = recommendation_repository.get_recommendation_by_keyword(keyword)
    if not rec:
        return None, []
    items = recommendation_repository.get_items_by_recommendation_id(rec["id"])
    orderable = [i for i in items if i["is_orderable"]][:2]
    return rec["id"], [_to_agent_item(i) for i in orderable]

def _default_address_response(user_id: int):
    addr = address_repository.get_default_address_by_user_id(user_id)
    if not addr:
        return None
    return {"addressId": addr["id"], "recipientName": addr["recipient_name"],
            "recipientPhone": addr.get("recipient_phone"), "zipCode": addr.get("zip_code"),
            "addressLine1": addr["address_line1"], "addressLine2": addr.get("address_line2"),
            "deliveryRequest": addr.get("delivery_request"), "isDefault": addr["is_default"]}

def _pending_product(rec_item_id: int, product_name: str):
    return {"type": "product", "message": f"{product_name}을(를) 주문할까요?",
            "payload": {"recommendationItemId": rec_item_id, "actions": ["order_now", "add_to_cart", "reject"]}}

def start_shopping(req: ShoppingRequest) -> AgentResponse:
    user = user_repository.get_user_by_id(req.userId)
    if not user:
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    keyword = _detect_keyword(req.message)
    if keyword == "clarification":
        conv = conversation_repository.create_conversation({"user_id": req.userId, "status": "intent_detected", "stage": "idle", "keyword": "clarification"})
        return AgentResponse(conversationId=conv["id"], status="intent_detected", stage="idle",
                             assistantMessage="어떤 상품을 찾으시나요? 좀 더 자세히 말씀해 주세요.",
                             pendingConfirmation={"type": "clarification"})
    existing_conv = conversation_repository.get_conversation_by_keyword(req.userId, keyword)
    conv = existing_conv or conversation_repository.create_conversation({"user_id": req.userId, "status": "waiting_user_confirmation", "stage": "product_confirming", "keyword": keyword})
    rec_id, items = _get_rec_items(keyword)
    history = purchase_history_repository.get_history_by_keyword(req.userId, keyword)
    product_name = history["product_name"] if history else (items[0].productName if items else "상품")
    first_item_id = items[0].recommendationItemId if items else None
    return AgentResponse(
        conversationId=conv["id"], status="waiting_user_confirmation", stage="product_confirming",
        assistantMessage=f"{product_name}을(를) 찾았어요. 이걸로 주문할까요?",
        recommendationId=rec_id, recommendations=items,
        pendingConfirmation=_pending_product(first_item_id, product_name) if first_item_id else None
    )

def get_conversation(conversation_id: int) -> AgentResponse:
    conv = conversation_repository.get_conversation_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail={"category": "CONVERSATION_ERROR", "code": "CONVERSATION_NOT_FOUND", "message": "대화를 찾을 수 없습니다."})
    rec = recommendation_repository.get_recommendation_by_conversation_id(conversation_id)
    items, rec_id = [], None
    if rec:
        rec_id = rec["id"]
        raw = recommendation_repository.get_items_by_recommendation_id(rec["id"])
        items = [_to_agent_item(i) for i in raw if i["is_orderable"]][:2]
    return AgentResponse(conversationId=conv["id"], status=conv["status"], stage=conv["stage"],
                         assistantMessage="현재 대화 상태입니다.", recommendationId=rec_id, recommendations=items)

def send_message(conversation_id: int, req: MessageRequest) -> AgentResponse:
    conv = conversation_repository.get_conversation_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail={"category": "CONVERSATION_ERROR", "code": "CONVERSATION_NOT_FOUND", "message": "대화를 찾을 수 없습니다."})
    action, message = req.action, req.message.strip()
    if action == "checkout_cart":
        conv["stage"] = "address_confirming"
        return AgentResponse(conversationId=conversation_id, status=conv["status"], stage="address_confirming",
                             assistantMessage="배송지를 확인해 주세요.", deliveryAddress=_default_address_response(conv["user_id"]))
    if action == "continue_shopping":
        conv["stage"] = "idle"
        return AgentResponse(conversationId=conversation_id, status=conv["status"], stage="idle",
                             assistantMessage="계속 쇼핑하시겠어요? 원하시는 상품을 말씀해 주세요.")
    if "취소" in message:
        conv["stage"] = "cancelled"; conv["status"] = "cancelled"
        return AgentResponse(conversationId=conversation_id, status="cancelled", stage="cancelled", assistantMessage="주문이 취소되었습니다.")
    if message in CONFIRM_MESSAGES and conv["stage"] == "address_confirming":
        conv["stage"] = "completed"; conv["status"] = "order_completed"
        return AgentResponse(conversationId=conversation_id, status="order_completed", stage="completed", assistantMessage="주문이 완료되었습니다! 감사합니다.")
    return AgentResponse(conversationId=conversation_id, status=conv["status"], stage=conv["stage"],
                         assistantMessage="죄송해요, 잘 이해하지 못했어요. 다시 말씀해 주시겠어요?",
                         pendingConfirmation={"type": "clarification"})

def confirm_action(conversation_id: int, req: ConfirmRequest) -> AgentResponse:
    conv = conversation_repository.get_conversation_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail={"category": "CONVERSATION_ERROR", "code": "CONVERSATION_NOT_FOUND", "message": "대화를 찾을 수 없습니다."})
    rec = recommendation_repository.get_recommendation_by_conversation_id(conversation_id)
    if req.action == "order_now":
        conv["stage"] = "address_confirming"
        return AgentResponse(conversationId=conversation_id, status=conv["status"], stage="address_confirming",
                             assistantMessage="배송지를 확인해 주세요.", deliveryAddress=_default_address_response(conv["user_id"]),
                             recommendationId=rec["id"] if rec else None)
    if req.action == "add_to_cart":
        return AgentResponse(conversationId=conversation_id, status=conv["status"], stage="product_confirming",
                             assistantMessage="장바구니에 담겼습니다. 계속 쇼핑하시겠어요, 아니면 바로 결제하시겠어요?",
                             recommendationId=rec["id"] if rec else None,
                             pendingConfirmation={"type": "product", "message": "어떻게 하시겠어요?",
                                                  "payload": {"actions": ["continue_shopping", "checkout_cart"]}})
    if req.action == "reject":
        if not rec:
            return AgentResponse(conversationId=conversation_id, status=conv["status"], stage="idle",
                                 assistantMessage="다른 후보가 없습니다. 원하시는 상품을 말씀해 주세요.",
                                 pendingConfirmation={"type": "clarification"})
        items = recommendation_repository.get_items_by_recommendation_id(rec["id"])
        orderable = [i for i in items if i["is_orderable"]]
        current_idx = next((idx for idx, i in enumerate(orderable) if i["id"] == req.recommendationItemId), -1)
        next_items = orderable[current_idx + 1:] if current_idx >= 0 else orderable[1:]
        if next_items:
            nxt = next_items[0]
            return AgentResponse(conversationId=conversation_id, status=conv["status"], stage="product_confirming",
                                 assistantMessage=f"{nxt['product_name']} 어떠세요?", recommendationId=rec["id"],
                                 recommendations=[_to_agent_item(nxt)],
                                 pendingConfirmation=_pending_product(nxt["id"], nxt["product_name"]))
        return AgentResponse(conversationId=conversation_id, status=conv["status"], stage="idle",
                             assistantMessage="다른 후보가 없습니다. 원하시는 상품을 말씀해 주세요.",
                             pendingConfirmation={"type": "clarification"})
    raise HTTPException(status_code=400, detail="Invalid action")
