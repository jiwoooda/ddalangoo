"""
LangGraph 추천 후보를 백엔드 recommendation 저장소와 동기화한다.

현재는 mock repository에 저장하지만, 나중에 SQLAlchemy repository로 교체해도
agent_service/runtime/mapper의 호출 구조는 유지한다.
"""

from copy import deepcopy
from typing import Any

from app.repositories import recommendation_repository


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


def _snapshot_item(product: dict, rank: int) -> dict:
    return {
        "product_id": product.get("product_id") or 0,
        "product_name": product.get("product_name") or product.get("name") or "",
        "brand": product.get("brand"),
        "price": product.get("price") or product.get("current_price") or 0,
        "option_text": product.get("option_text"),
        "delivery_info": product.get("delivery_info") or product.get("delivery"),
        "delivery_fee": product.get("delivery_fee"),
        "rating": product.get("rating"),
        "review_count": product.get("review_count"),
        "image_url": product.get("image_url"),
        "product_url": product.get("product_url") or product.get("url"),
        "platform": product.get("platform"),
        "reason": product.get("reason") or product.get("explanation"),
        "rank": product.get("rank") or rank,
        "is_presented": rank == 1,
        "is_selected": bool(product.get("is_selected", rank == 1)),
        "is_orderable": product.get("is_orderable", True),
        "order_block_reason": product.get("order_block_reason"),
    }


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
