from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import product_repository, purchase_history_repository
from app.services import recommendation_scoring_service


def _first_keyword(state: dict) -> str | None:
    """ShoppingState에서 대표 검색 키워드를 꺼낸다."""
    keywords = state.get("keywords") or []
    if not keywords:
        return None
    return str(keywords[0])


def purchase_history_to_candidate(history: dict) -> dict[str, Any]:
    """purchase_histories row를 재구매 추천 후보 형태로 변환한다."""
    return {
        "product_id": history.get("product_id") or 0,
        "product_option_id": history.get("product_option_id"),
        "matched_purchase_history_id": history.get("id"),
        "product_name": history.get("product_name_snapshot") or history.get("product_name") or "",
        "brand": history.get("brand_snapshot") or history.get("brand"),
        "category": history.get("category_snapshot") or history.get("category"),
        "option_text": history.get("option_snapshot") or history.get("option_text"),
        "price": history.get("price_at_purchase") or 0,
        "platform": history.get("platform"),
        "product_url": history.get("product_url_snapshot") or history.get("product_url"),
        "selected_options": history.get("selected_options"),
        "rating": None,
        "review_count": None,
        "delivery_info": None,
        "delivery_fee": None,
        "is_sold_out": False,
        "is_orderable": bool(history.get("product_url_snapshot") or history.get("product_url")),
        "order_block_reason": None if history.get("product_url_snapshot") or history.get("product_url") else "product_url_missing",
        "reason": "이전에 구매한 이력이 있는 상품입니다.",
        "raw": {
            "source": "purchase_histories",
            "purchase_history": history,
        },
    }


async def get_reorder_candidates_from_db(
    db: AsyncSession,
    *,
    user_id: int,
    keywords: list[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """재구매 흐름에서 DB purchase_histories 기반 후보를 만든다."""
    if not keywords:
        histories = await purchase_history_repository.get_histories_by_user_id_db(
            db,
            user_id=user_id,
            limit=limit,
        )
    else:
        histories = []
        seen_history_ids: set[int] = set()
        for keyword in keywords:
            keyword_histories = await purchase_history_repository.get_histories_by_user_id_db(
                db,
                user_id=user_id,
                keyword=str(keyword),
                limit=limit,
            )
            for history in keyword_histories:
                history_id = history.get("id")
                if history_id in seen_history_ids:
                    continue
                histories.append(history)
                if history_id is not None:
                    seen_history_ids.add(history_id)
                if len(histories) >= limit:
                    break
            if len(histories) >= limit:
                break

    candidates = [purchase_history_to_candidate(history) for history in histories[:limit]]
    for candidate in candidates:
        product_id = candidate.get("product_id")
        if not product_id:
            continue
        product = await product_repository.get_product_by_id_db(db, product_id)
        if not product:
            continue
        candidate["image_url"] = product.get("image_url")
        candidate["delivery_info"] = product.get("current_delivery_info")
        candidate["delivery_type"] = product.get("delivery_type")
        candidate["rating"] = product.get("rating")
        candidate["review_count"] = product.get("review_count")
    return await recommendation_scoring_service.rank_candidates(
        candidates,
        keywords=keywords,
        intent="reorder",
        purchase_histories=histories,
        mode="rule_based_v1",
    )


async def get_product_pool_candidates_from_db(
    db: AsyncSession,
    *,
    state: dict,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """products 후보 pool에서 현재 키워드에 맞는 후보를 가져온다."""
    keywords = [str(keyword) for keyword in (state.get("keywords") or [])]
    candidates = await product_repository.search_product_candidates_db(
        db,
        keywords=keywords,
        limit=limit,
    )
    return await recommendation_scoring_service.rank_candidates(
        candidates,
        keywords=keywords,
        intent=state.get("intent") or "buy",
        condition=state.get("condition"),
        preference_context=(state.get("recommendation_context") or {}).get("preference_memory"),
        mode="rule_based_v1",
    )


def build_product_confirm_patch(candidate: dict, *, message_prefix: str | None = None) -> dict:
    """후보 1개를 사용자 확인 대기 상태로 바꾸는 state patch를 만든다."""
    product_name = candidate.get("product_name") or candidate.get("name") or "상품"
    price = candidate.get("price") or 0
    product_url = candidate.get("product_url")
    message = message_prefix or f"'{product_name}'을(를) 추천드릴게요. 이 상품으로 할까요?"

    if price:
        message = f"{message} ({price:,}원)"

    return {
        "selected_product": candidate,
        "product_url": product_url,
        "messages": [{"role": "assistant", "content": message}],
        "explanation": message,
        "pending_action": {
            "type": "product_confirm",
            "message": message,
            "payload": {
                "product_url": product_url,
                "actions": ["accept", "reject"],
            },
        },
        "stage": "product_confirming",
        "error": None,
    }


_PAYMENT_STAGES = {
    "payment_method_confirm",
    "address_confirm",
    "payment_password",
    "payment_processing",
    "cart_shopping",
    "completed",
    "cancelled",
    "failed",
}


async def hydrate_state_with_db_candidates(
    db: AsyncSession,
    *,
    state: dict,
    user_id: int,
) -> dict:
    """
    LangGraph 결과에 DB 후보를 보강한다.

    - reorder: purchase_histories를 우선 사용한다.
    - 일반 구매: 외부 검색 결과가 없을 때 products 후보 pool을 fallback으로 사용한다.
    """
    # 결제 단계에서는 후보를 교체하지 않는다.
    # reorder intent인 경우 구매 이력 후보를 주입하면 stage: "product_confirming"으로
    # 덮어써져 LangGraph 체크포인트가 오염된다.
    if state.get("stage") in _PAYMENT_STAGES:
        return state

    intent = state.get("intent")
    existing_candidates = state.get("recommended_products") or state.get("search_results") or []

    if intent == "reorder":
        reorder_candidates = await get_reorder_candidates_from_db(
            db,
            user_id=user_id,
            keywords=[str(keyword) for keyword in (state.get("keywords") or [])],
        )
        if reorder_candidates:
            first_candidate = reorder_candidates[0]
            patch = build_product_confirm_patch(
                first_candidate,
                message_prefix=(
                    f"이전에 구매하셨던 '{first_candidate.get('product_name', '상품')}'을(를) "
                    "다시 주문할까요?"
                ),
            )
            return {
                **state,
                "search_results": reorder_candidates,
                "recommended_products": reorder_candidates,
                **patch,
            }

    should_try_product_pool = (
        intent in {"buy", "ask", "refine", "compare_platforms"}
        and not existing_candidates
        and state.get("error") in {None, "no_results", "product_agent_parse_error"}
    )
    if not should_try_product_pool:
        return state

    product_candidates = await get_product_pool_candidates_from_db(
        db,
        state=state,
    )
    if not product_candidates:
        return state

    first_candidate = product_candidates[0]
    patch = build_product_confirm_patch(
        first_candidate,
        message_prefix=f"저장된 상품 목록에서 '{_first_keyword(state) or '요청하신 상품'}' 후보를 찾았어요.",
    )
    return {
        **state,
        "search_results": product_candidates,
        "recommended_products": product_candidates,
        "explanation": patch["pending_action"]["message"],
        **patch,
    }
