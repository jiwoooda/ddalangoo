"""
Platform Agent Node.

역할: 플랫폼 선택 + search_product() 호출 → search_results 반환.
추천/랭킹/결제는 하지 않는다.
"""
import json
from typing import Any
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from src.state.schema import ShoppingState
from src.prompts.platform_prompt import PLATFORM_AGENT_PROMPT
from src.tools.mock_tools import mock_search_product

_llm: ChatAnthropic | None = None

CONDITION_MAP = {
    "최저가": "price_asc",
    "가성비": "value",
    "빠른배송": "delivery_fast",
    "인기순": "popularity",
    "리뷰좋은": "review_score",
    "무료배송": "free_shipping",
}

PLATFORM_DEFAULTS_BY_CONDITION = {
    "최저가": ["naver"],
    "가성비": ["naver"],
    "빠른배송": ["coupang"],
}

PLATFORM_DEFAULTS_BY_KEYWORD = {
    "과일": "kurly", "딸기": "kurly", "채소": "kurly", "정육": "kurly",
    "화장품": "oliveyoung", "뷰티": "oliveyoung",
    "패션": "musinsa", "의류": "musinsa", "신발": "musinsa",
}


def _get_llm() -> ChatAnthropic:
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(
            model="claude-sonnet-4-6",
            temperature=0,
            max_tokens=1024,
        )
    return _llm


def _select_platforms(state: ShoppingState, recommendation_context: dict) -> list[str]:
    """플랫폼 선택 우선순위 로직."""
    override = state.get("override_platform")
    if override:
        return [override]

    target = state.get("target_platforms") or []
    if target:
        return target

    # preference_memory platform_pattern 매칭
    pref = recommendation_context.get("preference_memory", {})
    platform_pattern = pref.get("platform_pattern", {})
    keywords = state.get("keywords") or []
    for kw in keywords:
        matched = platform_pattern.get(kw)
        if matched:
            return [matched]

    # 상품군 기반 선택
    for kw in keywords:
        for kw_key, platform in PLATFORM_DEFAULTS_BY_KEYWORD.items():
            if kw_key in kw.lower():
                return [platform]

    # condition 기반
    condition = state.get("condition")
    if condition and condition in PLATFORM_DEFAULTS_BY_CONDITION:
        return PLATFORM_DEFAULTS_BY_CONDITION[condition]

    tried = state.get("tried_platforms") or []
    defaults = [p for p in ["naver", "coupang"] if p not in tried]
    return defaults if defaults else ["naver"]


def _filter_results(
    products: list[dict[str, Any]],
    exclude_keywords: list[str],
) -> list[dict[str, Any]]:
    """필터링: 품절, URL/가격 누락, exclude_keywords."""
    filtered = []
    for p in products:
        if p.get("is_sold_out"):
            continue
        if not p.get("product_url"):
            continue
        if p.get("price") is None:
            continue
        name = p.get("product_name", "").lower()
        if any(ex.lower() in name for ex in exclude_keywords):
            continue
        filtered.append(p)
    return filtered


def platform_agent_node(state: ShoppingState, recommendation_context: dict | None = None) -> dict:
    """
    Platform Agent.
    역할: 플랫폼 선택 + search_product() → search_results 갱신.
    추천/결제는 하지 않는다.
    """
    recommendation_context = recommendation_context or {}
    keywords = state.get("keywords") or []
    exclude_keywords = state.get("exclude_keywords") or []
    condition = state.get("condition")

    if not keywords or all(k in ["그거", "저번에", "그것", "저것"] for k in keywords):
        return {
            "search_results": [],
            "stage": "idle",
            "error": "invalid_keywords",
            "last_agent": "platform_agent",
        }

    selected_platforms = _select_platforms(state, recommendation_context)
    sort_used = CONDITION_MAP.get(condition, "relevance") if condition else "relevance"
    query = " ".join(keywords)

    # Mock search_product 호출
    raw_results = mock_search_product(
        query=query,
        platforms=selected_platforms,
        condition=sort_used,
    )

    search_results = _filter_results(raw_results, exclude_keywords)

    tried_platforms = list(set((state.get("tried_platforms") or []) + selected_platforms))

    if not search_results:
        return {
            "search_results": [],
            "tried_platforms": tried_platforms,
            "selected_platform": selected_platforms[0] if selected_platforms else None,
            "stage": "idle",
            "error": "no_results",
            "last_agent": "platform_agent",
        }

    return {
        "search_results": search_results,
        "tried_platforms": tried_platforms,
        "selected_platform": selected_platforms[0] if len(selected_platforms) == 1 else "multi",
        "stage": "searching",
        "error": None,
        "last_agent": "platform_agent",
    }
