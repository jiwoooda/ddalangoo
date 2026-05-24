"""
Memory Agent Node.

역할:
  [Context Loading]  사용자 프로필/구매 이력/선호 조회 → recommendation_context 생성 → store 저장.
  [Tool Dispatch]    tool_calls를 State에 올려 backend가 실행하도록 위임.

호출 시점:
  - router → memory_agent (reorder intent)          : context loading + search tool
  - payment_agent → memory_agent (결제 완료 후)     : conversation summary tool only
"""
import re
from typing import Any, Optional
from langgraph.store.base import BaseStore

from src.state.schema import ShoppingState, MemoryState, bridge_memory_to_shopping
from src.tools.mock_tools import (
    mock_get_user,
    mock_get_default_address,
    mock_get_preference_memory,
    mock_count_purchases,
    mock_keyword_search_history,
    mock_vector_search_personal,
    mock_vector_search_collective,
)

PERSONAL_VECTOR_THRESHOLD = 20


def _get_latest_user_text(state: ShoppingState) -> str:
    messages = state.get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, dict):
            content = msg.get("content")
            role = msg.get("role") or msg.get("type")
            if content and role in (None, "user", "human"):
                return str(content)
        else:
            content = getattr(msg, "content", None)
            msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
            if content and msg_type in (None, "human", "user"):
                return str(content)
    return ""


def _candidate_to_search_result(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_name": candidate.get("product_name", ""),
        "price": candidate.get("price_at_purchase", 0),
        "rating": None,
        "review_count": None,
        "delivery": None,
        "delivery_fee": None,
        "platform": candidate.get("platform", ""),
        "image_url": None,
        "product_url": candidate.get("product_url", ""),
        "option_text": candidate.get("option_text"),
        "selected_options": candidate.get("selected_options") or {},
        "product_id": candidate.get("product_id"),
        "product_option_id": candidate.get("product_option_id"),
        "purchase_history_id": candidate.get("purchase_history_id"),
        "score": candidate.get("score"),
        "is_sold_out": False,
        "raw": candidate,
    }


def _fallback_resolve_reorder_memory(
    user_id: str,
    query: str,
    keywords: list[str],
    top_k: int = 5,
) -> dict[str, Any]:
    history = mock_keyword_search_history(user_id, keywords or [query], limit=top_k)
    candidates = []
    for item in history:
        candidates.append({
            "purchase_history_id": item.get("id"),
            "product_id": item.get("product_id"),
            "product_option_id": item.get("product_option_id"),
            "product_name": item.get("product_name"),
            "product_url": item.get("product_url"),
            "option_text": item.get("option_text"),
            "selected_options": item.get("selected_options") or {},
            "price_at_purchase": item.get("price_at_purchase", 0),
            "platform": item.get("platform"),
            "purchased_at": item.get("purchased_at"),
            "score": 0.8,
            "reason": "mock keyword match",
        })

    if not candidates:
        return {
            "resolution_type": "no_match",
            "resolved": False,
            "needs_user_selection": False,
            "selected_candidate": None,
            "candidates": [],
        }

    if len(candidates) == 1:
        return {
            "resolution_type": "resolved",
            "resolved": True,
            "needs_user_selection": False,
            "selected_candidate": candidates[0],
            "candidates": candidates,
        }

    return {
        "resolution_type": "ambiguous",
        "resolved": False,
        "needs_user_selection": True,
        "selected_candidate": None,
        "candidates": candidates[:3],
        "question": "이전에 구매한 상품이 여러 개 있어요. 어떤 상품으로 다시 주문할까요?",
    }


def _resolve_reorder_memory(
    user_id: str,
    query: str,
    keywords: list[str],
    top_k: int = 5,
) -> dict[str, Any]:
    try:
        from app.services.memory_tools import resolve_reorder_memory

        return resolve_reorder_memory(
            user_id=int(user_id),
            query=query,
            keywords=keywords,
            top_k=top_k,
        )
    except Exception:
        return _fallback_resolve_reorder_memory(user_id, query, keywords, top_k)


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


def _summarize_messages(messages: list) -> str:
    """메시지 요약 (임시: 최근 5개 단순 연결 / TODO: Claude API로 교체)."""
    recent = messages[-5:] if len(messages) > 5 else messages
    parts = []
    for msg in recent:
        if isinstance(msg, dict):
            role, content = msg.get("role", ""), str(msg.get("content", ""))[:50]
        else:
            role = getattr(msg, "type", "") or getattr(msg, "role", "")
            content = str(getattr(msg, "content", ""))[:50]
        parts.append(f"[{role}] {content}")
    return " | ".join(parts)


def _extract_reorder_keyword(user_input: str, keywords: list[str]) -> str:
    """재구매 키워드 추출: state keywords 우선, 없으면 간단 패턴 매칭."""
    if keywords:
        return " ".join(keywords)
    for pattern in [r"저번에\s*산\s*(\S+)", r"(\S+)\s*다시", r"(\S+)\s*또"]:
        m = re.search(pattern, user_input)
        if m:
            return m.group(1)
    return user_input


def _build_tool_calls(state: ShoppingState) -> list[dict[str, Any]]:
    """State를 보고 필요한 tool_calls 목록을 생성한다."""
    calls: list[dict[str, Any]] = []
    intent = state.get("intent")
    messages = state.get("messages") or []

    # 1. 메시지 수 초과 → 대화 요약 저장
    if len(messages) > 10:
        summary = _summarize_messages(messages)
        calls.append({
            "tool": "save_conversation_summary",
            "args": {
                "conversation_id": state.get("conversation_id"),
                "summary": summary,
                "message_count": len(messages),
            },
        })

    return calls


def memory_agent_node(state: ShoppingState, store: Optional[BaseStore] = None) -> dict:
    """
    Memory Agent.

    [결제 완료 후] stage=="completed": tool_calls만 방출하고 종료.
    [reorder 탐색] intent=="reorder":  context loading + tool_calls 방출.
    """
    stage = state.get("stage")
    intent = state.get("intent")
    user_id = state.get("user_id", "")
    keywords = state.get("keywords") or []

    tool_calls = _build_tool_calls(state)
    updates: dict[str, Any] = {"last_agent": "memory_agent", "tool_calls": tool_calls or None}

    # 메시지 요약이 생성됐다면 state에도 기록
    if len(state.get("messages") or []) > 10:
        updates["conversation_summary"] = _summarize_messages(state.get("messages") or [])

    # ── 결제 완료 후 호출: context loading 불필요 ──
    if stage == "completed":
        return updates

    # ── Context Loading (reorder / 기타) ──
    recommendation_context = get_recommendation_context(
        user_id=user_id,
        keywords=keywords,
        intent=intent,
    )

    if store is not None:
        store.put(
            ("recommendation_context", user_id),
            "latest",
            recommendation_context,
        )

    base = {
        **bridge_memory_to_shopping({}),
        "recommendation_context": recommendation_context,
        **updates,
    }

    # reorder: resolve only top-k purchase history candidates.
    if intent == "reorder":
        query = _get_latest_user_text(state) or _extract_reorder_keyword("", keywords)
        resolver_result = _resolve_reorder_memory(
            user_id=user_id,
            query=query,
            keywords=keywords,
            top_k=5,
        )
        search_results = [
            _candidate_to_search_result(candidate)
            for candidate in (resolver_result.get("candidates") or [])
        ]
        return {
            **base,
            "reorder_resolution": resolver_result,
            "search_results": search_results,
            "stage": "searching",
        }

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
