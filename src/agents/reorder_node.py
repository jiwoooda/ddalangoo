"""
Reorder Node.

역할: 구매 이력 스냅샷(memory_agent가 search_results에 채워줌) → URL 유효성 확인
- URL 유효: product_confirm pending_action 설정 → respond (사용자 확인 대기)
- URL 무효/없음: stage=searching, keywords 유지 → platform_agent fallback

LLM 호출 없음. 결정 로직만.
"""
from src.state.schema import ShoppingState
from src.tools.mock_tools import mock_validate_product_url


def reorder_node(state: ShoppingState) -> dict:
    """
    Reorder Node.

    memory_agent → reorder_node → respond (확인) → payment_agent
                               └→ platform_agent (URL 실패 fallback)
    """
    search_results = state.get("search_results") or []
    keywords = state.get("keywords") or []

    # 구매 이력에서 첫 번째 유효 후보 선택
    candidate = None
    for item in search_results:
        url = item.get("product_url", "")
        if url and mock_validate_product_url(url):
            candidate = item
            break

    if candidate is None:
        # URL이 없거나 모두 실패 → platform_agent fallback
        return {
            "stage": "searching",
            "error": "reorder_url_failed",
            "search_results": [],
        }

    product_url = candidate["product_url"]
    selected_product = {
        "product_name": candidate.get("product_name", ""),
        "price": candidate.get("price", 0),
        "platform": candidate.get("platform", ""),
        "product_url": product_url,
    }

    pending_action = {
        "type": "product_confirm",
        "message": (
            f"이전에 구매하셨던 '{candidate.get('product_name', '상품')}'을(를) "
            f"다시 주문할까요? ({candidate.get('price', 0):,}원)"
        ),
        "payload": {"product_url": product_url},
    }

    return {
        "selected_product": selected_product,
        "product_url": product_url,
        "pending_action": pending_action,
        "stage": "product_confirming",
        "error": None,
    }
