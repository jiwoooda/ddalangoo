"""
LangGraph 추천 후보를 백엔드 recommendation 저장소와 동기화한다.

현재는 mock repository에 저장하지만, 나중에 SQLAlchemy repository로 교체해도
agent_service/runtime/mapper의 호출 구조는 유지한다.
"""

from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import (
    crawled_product_snapshot_repository,
    product_repository,
    recommendation_repository,
)
from app.services import recommendation_scoring_service
from app.utils.product_url_contract import canonical_product_url_for_platform


def _candidate_products(state: dict) -> list[dict[str, Any]]:
    recommended = state.get("recommended_products") or []
    search_results = state.get("search_results") or []
    return [deepcopy(p) for p in (recommended or search_results)]


def _recommendation_item_id(product: dict) -> int | None:
    return (
        product.get("recommendation_item_id")
        or product.get("recommendationItemId")
        or product.get("id")
    )


def _snapshot_item(product: dict, rank: int, is_presented: bool = False, is_selected: bool = False) -> dict:
    return {
        "product_id": product.get("product_id") or 0,
        "product_name": product.get("product_name") or product.get("name") or "",
        "brand": product.get("brand"),
        "category": product.get("category"),
        "price": product.get("price") or product.get("current_price") or 0,
        "original_price": product.get("original_price"),
        "discount_rate": product.get("discount_rate"),
        "option_text": product.get("option_text"),
        "delivery_info": product.get("delivery_info") or product.get("delivery"),
        "delivery_fee": product.get("delivery_fee"),
        "rating": product.get("rating"),
        "review_count": product.get("review_count"),
        "image_url": product.get("image_url"),
        "product_url": product.get("product_url") or product.get("url"),
        "platform": product.get("platform"),
        "score": product.get("score"),
        "score_detail": product.get("score_detail"),
        "reason": product.get("reason") or product.get("explanation"),
        "rank": product.get("rank") or rank,
        "is_presented": bool(product.get("is_presented", is_presented)),
        "is_selected": bool(product.get("is_selected", is_selected)),
        "is_orderable": product.get("is_orderable", True),
        "order_block_reason": product.get("order_block_reason"),
        "matched_purchase_history_id": product.get("matched_purchase_history_id"),
    }


def _first_keyword(state: dict) -> str | None:
    """검색/크롤링 snapshot에 남길 대표 키워드를 가져온다."""
    keywords = state.get("keywords") or []
    if not keywords:
        return None
    return str(keywords[0])


def _candidate_platform(candidate: dict, state: dict) -> str:
    """candidate에 플랫폼이 없으면 state의 선택 플랫폼을 fallback으로 쓴다."""
    return candidate.get("platform") or state.get("selected_platform") or "unknown"


def _candidate_to_normalized_snapshot(candidate: dict, state: dict) -> dict:
    """
    검색/크롤링 candidate를 crawled_product_snapshots.normalized_* 업데이트 값으로 변환한다.

    지금 단계의 정제는 LLM 정제가 아니라 백엔드 필드 정규화다.
    원본값은 raw_*에 보존하고, products upsert에 필요한 값만 normalized_*에 복사한다.
    """
    product_name = candidate.get("normalized_name") or candidate.get("product_name") or candidate.get("name")
    category = candidate.get("normalized_category") or candidate.get("category") or _first_keyword(state)

    return {
        "normalized_name": product_name,
        "normalized_brand": candidate.get("brand"),
        "normalized_category": category,
        "normalized_sub_category": candidate.get("sub_category"),
        "normalized_volume": candidate.get("volume") or candidate.get("option_text"),
        "normalized_price": candidate.get("price") or candidate.get("current_price"),
        "normalized_original_price": candidate.get("original_price"),
        "normalized_discount_rate": candidate.get("discount_rate"),
        "normalized_delivery_type": candidate.get("delivery_info") or candidate.get("delivery"),
        "normalized_rating": candidate.get("rating"),
        "normalized_review_count": candidate.get("review_count"),
        "normalized_is_available": not bool(candidate.get("is_sold_out")),
        "normalization_status": "normalized",
    }


async def _persist_candidate_product_snapshot_db(
    db: AsyncSession,
    product: dict,
    state: dict,
) -> dict:
    """
    추천 후보를 raw snapshot으로 저장한 뒤, 정제값을 채우고 products에 upsert한다.

    반환된 product dict에는 product_id와 crawled_product_snapshot_id를 붙여서
    recommendation_items snapshot 저장 단계에서 그대로 사용할 수 있게 한다.
    """
    if product.get("crawled_product_snapshot_id"):
        return product

    snapshot = await crawled_product_snapshot_repository.create_crawled_product_snapshot_db(
        db,
        {
            **product,
            "platform": _candidate_platform(product, state),
            "crawl_keyword": _first_keyword(state),
            "crawl_source": product.get("crawl_source") or "search",
        },
    )
    normalized_snapshot = await crawled_product_snapshot_repository.update_snapshot_normalization_db(
        db,
        snapshot["id"],
        _candidate_to_normalized_snapshot(product, state),
    )
    if not normalized_snapshot:
        return product

    saved_product = await product_repository.upsert_product_from_snapshot_db(
        db,
        normalized_snapshot,
        default_category=_first_keyword(state) or "unknown",
    )

    product["product_id"] = saved_product["id"]
    product["crawled_product_snapshot_id"] = normalized_snapshot["id"]
    product["platform"] = product.get("platform") or normalized_snapshot.get("platform")
    return product


def _attach_item_id(product: dict, item_id: int) -> dict:
    product["recommendation_item_id"] = item_id
    product["recommendationItemId"] = item_id
    return product


def _attach_pending_action(state: dict, selected_product: dict | None) -> dict | None:
    pending_action = deepcopy(state.get("pending_action"))
    item_id = _recommendation_item_id(selected_product or {})
    if not pending_action or pending_action.get("type") != "product_confirm" or not item_id:
        return pending_action

    payload = pending_action.get("payload") or {}
    payload["recommendationItemId"] = item_id
    payload["recommendation_item_id"] = item_id
    pending_action["payload"] = payload
    return pending_action


def _same_product(left: dict, right: dict) -> bool:
    """추천 후보 동일성 판단에서 검색 URL은 상품 식별값으로 쓰지 않는다."""
    left_id = _recommendation_item_id(left)
    right_id = _recommendation_item_id(right)
    if left_id and right_id:
        return left_id == right_id

    left_name = left.get("product_name") or left.get("name")
    right_name = right.get("product_name") or right.get("name")
    if left_name and right_name and left_name == right_name:
        return True

    left_platform = left.get("platform") or right.get("platform")
    right_platform = right.get("platform") or left.get("platform")
    left_url = canonical_product_url_for_platform(
        left_platform,
        left.get("canonical_product_url"),
        left.get("product_url"),
        left.get("url"),
    )
    right_url = canonical_product_url_for_platform(
        right_platform,
        right.get("canonical_product_url"),
        right.get("product_url"),
        right.get("url"),
    )
    return bool(left_url and right_url and left_url == right_url)


def _presented_product_from_state(state: dict, candidates: list[dict]) -> dict | None:
    """
    현재 사용자에게 읽어준 후보를 찾는다.

    selected_product는 '사용자가 고른 상품'이라기보다 현재 설명 중인 상품으로 쓰이는 경우가 많다.
    그래서 노출 여부는 selected_product 또는 current_product_index 기준으로 판단한다.
    """
    selected_product = state.get("selected_product")
    if isinstance(selected_product, dict):
        for product in candidates:
            if _same_product(product, selected_product):
                return product

    current_index = state.get("current_product_index")
    if isinstance(current_index, int) and 0 <= current_index < len(candidates):
        return candidates[current_index]

    return candidates[0] if candidates else None


async def _update_recommendation_item_statuses_db(
    db: AsyncSession,
    attached: list[dict],
    presented_product: dict | None,
    should_mark_selected: bool,
) -> None:
    """추천 후보의 제시/선택 상태를 DB와 state dict에 반영한다."""
    if not presented_product:
        return

    presented_item_id = _recommendation_item_id(presented_product)
    if not presented_item_id:
        return

    presented_item = await recommendation_repository.mark_recommendation_item_presented_db(
        db,
        presented_item_id,
    )
    if should_mark_selected:
        presented_item = await recommendation_repository.mark_recommendation_item_selected_db(
            db,
            presented_item_id,
        )

    for product in attached:
        item_id = _recommendation_item_id(product)
        if item_id == presented_item_id:
            product["is_presented"] = True
            if presented_item:
                product["presented_at"] = presented_item.get("presented_at")
                product["is_selected"] = presented_item.get("is_selected", False)
        elif should_mark_selected:
            product["is_selected"] = False


def persist_and_attach_ids(state: dict, user_id: int, conversation_id: int) -> dict:
    """
    추천 후보를 저장하고 실제 recommendation_item_id를 state에 붙인다.

    가짜 fallback id는 만들지 않는다. 이미 id가 붙은 후보는 그대로 둔다.
    """
    candidates = _candidate_products(state)
    if not candidates:
        return state

    recommendation = recommendation_repository.get_recommendation_by_conversation_id(conversation_id)
    if not recommendation:
        recommendation = recommendation_repository.create_recommendation({
            "conversation_id": conversation_id,
            "user_id": user_id,
            "keyword": ",".join(state.get("keywords") or []),
            "status": "shown",
            "recommendation_type": state.get("intent") or "unknown",
            "summary": state.get("explanation") or "LangGraph 추천 후보",
        })

    attached: list[dict] = []
    for idx, product in enumerate(candidates, start=1):
        item_id = _recommendation_item_id(product)
        if not item_id:
            item = recommendation_repository.create_recommendation_item(
                recommendation_id=recommendation["id"],
                data=_snapshot_item(product, idx),
            )
            item_id = item["id"]
        attached.append(_attach_item_id(product, item_id))

    selected_product = deepcopy(state.get("selected_product"))
    if selected_product:
        selected_url = selected_product.get("product_url") or selected_product.get("url")
        selected_name = selected_product.get("product_name") or selected_product.get("name")
        matched = next(
            (
                p for p in attached
                if (selected_url and selected_url in (p.get("product_url"), p.get("url")))
                or (selected_name and selected_name == (p.get("product_name") or p.get("name")))
            ),
            attached[0],
        )
        selected_product = {**selected_product, **{
            "recommendation_item_id": _recommendation_item_id(matched),
            "recommendationItemId": _recommendation_item_id(matched),
        }}
    else:
        selected_product = attached[0]

    patch = {
        "recommended_products": attached,
        "selected_product": selected_product,
        "pending_action": _attach_pending_action({**state, "pending_action": state.get("pending_action")}, selected_product),
    }
    return {**state, **patch}


async def persist_and_attach_ids_db(
    db: AsyncSession,
    state: dict,
    user_id: int,
    conversation_id: int,
) -> dict:
    """
    추천 후보를 DB에 저장하고 실제 recommendation_item_id를 state에 붙인다.

    sync 버전은 mock repository용으로 남기고, DB 연결 흐름에서는 이 함수를 사용한다.
    """
    candidates = _candidate_products(state)
    if not candidates:
        return state
    if any(product.get("score") is None or not product.get("rank") for product in candidates):
        candidates = await recommendation_scoring_service.rank_candidates(
            candidates,
            keywords=[str(keyword) for keyword in (state.get("keywords") or [])],
            intent=state.get("intent") or "unknown",
            condition=state.get("condition"),
            purchase_histories=(state.get("recommendation_context") or {}).get("keyword_results"),
            preference_context=(state.get("recommendation_context") or {}).get("preference_memory"),
            mode="rule_based_v1",
        )

    presented_product = _presented_product_from_state(state, candidates)
    should_mark_selected = bool(state.get("user_confirmed_product"))

    recommendation = await recommendation_repository.get_recommendation_by_conversation_id_db(
        db,
        conversation_id,
    )
    if not recommendation:
        recommendation = await recommendation_repository.create_recommendation_db(
            db,
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "keyword": ",".join(state.get("keywords") or []),
                "status": "shown",
                "recommendation_type": state.get("intent") or "unknown",
                "summary": state.get("explanation") or "LangGraph 추천 후보",
                "intent_id": state.get("agent_intent_id"),
            },
        )

    attached: list[dict] = []
    for idx, product in enumerate(candidates, start=1):
        if not product.get("product_id"):
            try:
                product = await _persist_candidate_product_snapshot_db(
                    db,
                    product,
                    state,
                )
            except ValueError:
                # 이름이 없는 후보는 추천 snapshot만 저장하고 raw/product upsert는 건너뛴다.
                pass

        item_id = _recommendation_item_id(product)
        if not item_id:
            is_presented = presented_product is not None and _same_product(product, presented_product)
            item = await recommendation_repository.create_recommendation_item_db(
                db,
                recommendation_id=recommendation["id"],
                data=_snapshot_item(
                    product,
                    idx,
                    is_presented=is_presented,
                    is_selected=is_presented and should_mark_selected,
                ),
            )
            item_id = item["id"]
        attached.append(_attach_item_id(product, item_id))

    selected_product = deepcopy(state.get("selected_product"))
    if selected_product:
        selected_url = selected_product.get("product_url") or selected_product.get("url")
        selected_name = selected_product.get("product_name") or selected_product.get("name")
        matched = next(
            (
                p for p in attached
                if (selected_url and selected_url in (p.get("product_url"), p.get("url")))
                or (selected_name and selected_name == (p.get("product_name") or p.get("name")))
            ),
            attached[0],
        )
        selected_product = {
            **selected_product,
            "recommendation_item_id": _recommendation_item_id(matched),
            "recommendationItemId": _recommendation_item_id(matched),
        }
    else:
        selected_product = attached[0]

    # DB row가 이미 있던 후보도 현재 노출/선택 상태를 반영한다.
    presented_attached = _presented_product_from_state(
        {**state, "selected_product": selected_product},
        attached,
    )
    await _update_recommendation_item_statuses_db(
        db,
        attached,
        presented_attached,
        should_mark_selected,
    )
    selected_item_id = _recommendation_item_id(selected_product or {})
    if selected_item_id:
        matched_after_status = next(
            (
                product for product in attached
                if _recommendation_item_id(product) == selected_item_id
            ),
            None,
        )
        if matched_after_status:
            selected_product = {**selected_product, **matched_after_status}

    patch = {
        "recommended_products": attached,
        "selected_product": selected_product,
        "pending_action": _attach_pending_action(
            {**state, "pending_action": state.get("pending_action")},
            selected_product,
        ),
    }
    return {**state, **patch}
