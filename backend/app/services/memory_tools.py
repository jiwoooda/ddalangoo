"""
Memory Agent Tool 구현체.

Memory Agent(vendor)는 tool_calls를 state에 올려두고,
백엔드 서비스가 여기서 실제 실행한다.

tool 종류:
  - save_purchase_history     : deprecated no-op. purchase history is saved by payment_service
  - save_conversation_summary : 메시지 수 초과 시 대화 요약 저장
  - search_similar_purchases  : 재구매 시 유사 구매 이력 검색
"""
from typing import Any
from app.repositories import conversation_repository
from app.services import reorder_memory_resolver


def save_purchase_history(
    user_id: int,
    conversation_id: int,
    order_id: Any,
    product: dict[str, Any] | None = None,
    quantity: int = 1,
) -> dict[str, Any]:
    """Deprecated: payment_service is the only trigger for purchase history persistence."""
    return {
        "success": True,
        "skipped": True,
        "reason": "purchase_history_saved_by_payment_service",
    }


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
    """DB purchase_histories 기반 reorder resolver 결과를 tool 응답 형태로 변환한다."""
    resolution = reorder_memory_resolver.resolve_reorder_memory(
        user_id=user_id,
        query=query,
        keywords=[query] if query else [],
        top_k=top_k,
    )
    results = resolution.get("candidates") or []
    return {"success": True, "results": results, "count": len(results)}


def resolve_reorder_memory(
    user_id: int,
    query: str,
    keywords: list[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Resolve a reorder request against purchase history candidates."""
    return reorder_memory_resolver.resolve_reorder_memory(
        user_id=user_id,
        query=query,
        keywords=keywords or [],
        top_k=top_k,
    )


# tool 이름 → 함수 매핑
_TOOL_REGISTRY: dict[str, Any] = {
    "save_purchase_history": save_purchase_history,
    "save_conversation_summary": save_conversation_summary,
    "search_similar_purchases": search_similar_purchases,
    "resolve_reorder_memory": resolve_reorder_memory,
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
