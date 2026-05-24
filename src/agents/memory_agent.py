"""
Memory Agent Node.

역할: 사용자 프로필/구매 이력/선호 조회 → recommendation_context 생성 → store 저장.
ShoppingState에 과도한 context를 직접 주입하지 않는다.
bridge_memory_to_shopping()이 반환하는 최소값만 ShoppingState에 반영한다.
"""
from typing import Any, Optional
from langgraph.store.base import BaseStore

from src.state.schema import ShoppingState, MemoryState, bridge_memory_to_shopping
from src.tools.mock_tools import (
    mock_get_user,
    mock_get_default_address,
    mock_get_purchase_history,
    mock_get_preference_memory,
    mock_count_purchases,
    mock_keyword_search_history,
    mock_vector_search_personal,
    mock_vector_search_collective,
)

PERSONAL_VECTOR_THRESHOLD = 20


def _merge_recommendation_results(
    keyword_results: list[dict[str, Any]],
    personal_vector_results: list[dict[str, Any]],
    collective_vector_results: list[dict[str, Any]],
    intent: Optional[str] = None,
) -> list[dict[str, Any]]:
    merged = []
    seen: set = set()

    if intent == "reorder":
        sources = [
            ("keyword", keyword_results),
            ("personal_vector", personal_vector_results),
            ("collective_vector", collective_vector_results),
        ]
    else:
        sources = [
            ("personal_vector", personal_vector_results),
            ("keyword", keyword_results),
            ("collective_vector", collective_vector_results),
        ]

    for source, results in sources:
        for item in results:
            key = (
                item.get("product_url")
                or item.get("product_name_snapshot")
                or item.get("product_name")
                or item.get("id")
            )
            if not key or key in seen:
                continue
            item = dict(item)
            item["_memory_source"] = source
            merged.append(item)
            seen.add(key)

    return merged[:10]


def get_recommendation_context(
    user_id: str,
    keywords: list[str],
    intent: Optional[str] = None,
) -> dict[str, Any]:
    """
    추천용 Retrieval Context 생성.
    - reorder: keyword 우선
    - 구매 20개 미만: keyword + collective vector
    - 구매 20개 이상: keyword + personal vector + collective vector
    """
    user_profile = mock_get_user(user_id) or {}
    default_address = mock_get_default_address(user_id)
    preference_memory = mock_get_preference_memory(user_id)
    purchase_count = mock_count_purchases(user_id)

    query = " ".join(keywords)
    keyword_results = mock_keyword_search_history(user_id, keywords)

    use_personal_vector = purchase_count >= PERSONAL_VECTOR_THRESHOLD
    personal_vector_results = (
        mock_vector_search_personal(user_id, query) if use_personal_vector else []
    )

    age_group = user_profile.get("age_group")
    collective_vector_results = mock_vector_search_collective(
        query=query, age_group=age_group
    )

    if use_personal_vector:
        retrieval_mode = "hybrid_personal_collective"
    elif intent == "reorder":
        retrieval_mode = "keyword_only"
    else:
        retrieval_mode = "keyword_collective"

    merged_context = _merge_recommendation_results(
        keyword_results=keyword_results,
        personal_vector_results=personal_vector_results,
        collective_vector_results=collective_vector_results,
        intent=intent,
    )

    return {
        "user_profile": {
            "user_id": user_id,
            "name": user_profile.get("name"),
            "age_group": user_profile.get("age_group"),
            "default_address": default_address,
        },
        "preference_memory": preference_memory,
        "purchase_count": purchase_count,
        "retrieval_mode": retrieval_mode,
        "keyword_results": keyword_results,
        "personal_vector_results": personal_vector_results,
        "collective_vector_results": collective_vector_results,
        "merged_context": merged_context,
    }


def memory_agent_node(state: ShoppingState, store: Optional[BaseStore] = None) -> dict:
    """
    Memory Agent.
    역할:
    - reorder intent 처리 → 구매 이력 조회
    - 추천 retrieval context 생성
    - store에 recommendation_context 저장 (ShoppingState에 직접 주입하지 않음)

    반환: bridge_memory_to_shopping() 결과만 (last_agent만 설정)
    """
    user_id = state.get("user_id", "")
    keywords = state.get("keywords") or []
    intent = state.get("intent")

    recommendation_context = get_recommendation_context(
        user_id=user_id,
        keywords=keywords,
        intent=intent,
    )

    # Store에 recommendation_context 저장 (platform/product agent가 조회)
    if store is not None:
        store.put(
            ("recommendation_context", user_id),
            "latest",
            recommendation_context,
        )

    base = {
        **bridge_memory_to_shopping({}),
        "recommendation_context": recommendation_context,
    }

    # reorder: 구매 이력에서 상품 후보를 만들어 search_results에 제공
    if intent == "reorder":
        history = mock_keyword_search_history(user_id, keywords, limit=5)
        if history:
            search_results = [
                {
                    "product_name": item.get("product_name_snapshot", ""),
                    "price": item.get("price_at_purchase", 0),
                    "rating": None,
                    "review_count": None,
                    "delivery": None,
                    "delivery_fee": None,
                    "platform": item.get("platform", ""),
                    "image_url": None,
                    "product_url": item.get("product_url", ""),
                    "is_sold_out": False,
                    "raw": item,
                }
                for item in history
            ]
            return {**base, "search_results": search_results, "stage": "searching"}

    return base


def get_recommendation_context_from_store(
    user_id: str,
    store: Optional[BaseStore] = None,
) -> dict[str, Any]:
    """Store에서 recommendation_context 조회."""
    if store is None:
        return {}
    item = store.get(("recommendation_context", user_id), "latest")
    if item is None:
        return {}
    return item.value if hasattr(item, "value") else {}
