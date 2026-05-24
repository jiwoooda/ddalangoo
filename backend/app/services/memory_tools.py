"""
Memory Agent Tool 구현체.

Memory Agent(vendor)는 tool_calls를 state에 올려두고,
백엔드 서비스가 여기서 실제 실행한다.

tool 종류:
  - save_purchase_history     : 결제 완료 후 구매 이력 저장
  - save_conversation_summary : 메시지 수 초과 시 대화 요약 저장
  - search_similar_purchases  : 재구매 시 유사 구매 이력 검색
"""
from typing import Any
from app.repositories import order_repository, purchase_history_repository, conversation_repository


def save_purchase_history(
    user_id: int,
    conversation_id: int,
    order_id: int,
) -> dict[str, Any]:
    """결제 완료 후 order_items 기반으로 purchase_histories 저장."""
    order = order_repository.get_order_by_id(order_id)
    if not order:
        return {"success": False, "error": f"order {order_id} not found"}

    items = order_repository.get_order_items_by_order_id(order_id)
    if not items:
        return {"success": False, "error": "order_items empty"}

    saved = []
    for item in items:
        h = purchase_history_repository.create_history({
            "user_id": user_id,
            "conversation_id": conversation_id,
            "order_id": order_id,
            "product_id": item.get("product_id"),
            "product_name": item.get("product_name", ""),
            "option_text": item.get("option_text"),
            "price_at_purchase": item.get("unit_price", 0),
            "quantity": item.get("quantity", 1),
            "total_price": item.get("total_price", 0),
            "platform": order.get("platform", "naver"),
        })
        saved.append(h["id"])

    return {"success": True, "count": len(saved), "history_ids": saved}


def save_conversation_summary(
    conversation_id: int,
    summary: str,
    message_count: int,
) -> dict[str, Any]:
    """대화 요약을 conversation 레코드에 저장."""
    conv = conversation_repository.get_conversation_by_id(conversation_id)
    if not conv:
        return {"success": False, "error": f"conversation {conversation_id} not found"}

    conversation_repository.update_conversation(conversation_id, {
        "summary": summary,
        "summary_message_count": message_count,
    })
    return {"success": True}


def search_similar_purchases(
    user_id: int,
    query: str,
    top_k: int = 3,
) -> dict[str, Any]:
    """구매 이력에서 query와 유사한 상품을 키워드 매칭으로 검색."""
    histories = purchase_history_repository.get_histories_by_user_id(user_id)
    query_lower = query.lower()

    matched = [
        h for h in histories
        if query_lower in h.get("product_name", "").lower()
        or query_lower in (h.get("keyword") or "").lower()
        or query_lower in (h.get("category") or "").lower()
    ]

    results = [
        {
            "product_name": h["product_name"],
            "price_at_purchase": h.get("price_at_purchase", 0),
            "quantity": h.get("quantity", 1),
            "platform": h.get("platform"),
            "purchased_at": h.get("purchased_at"),
        }
        for h in matched[:top_k]
    ]
    return {"success": True, "results": results, "count": len(results)}


# tool 이름 → 함수 매핑
_TOOL_REGISTRY: dict[str, Any] = {
    "save_purchase_history": save_purchase_history,
    "save_conversation_summary": save_conversation_summary,
    "search_similar_purchases": search_similar_purchases,
}

# search 계열 tool은 결과를 state에 주입해야 함
_SEARCH_TOOLS = {"search_similar_purchases"}


def execute_tool(tool_name: str, args: dict) -> dict[str, Any]:
    fn = _TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {"success": False, "error": f"unknown tool: {tool_name}"}
    try:
        return fn(**args)
    except Exception as e:
        return {"success": False, "error": str(e)}
