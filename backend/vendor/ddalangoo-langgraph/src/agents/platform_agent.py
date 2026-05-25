"""
Platform Agent Node.

역할: 플랫폼 선택 + search_product() 호출 → search_results 반환.
추천/랭킹/결제는 하지 않는다.

Kurly 제안 로직:
- naver/coupang 검색 후 신선식품 키워드가 있고 kurly를 아직 안 써봤으면
  product_agent를 건너뛰고 바로 "마켓컬리에서도 찾아볼까요?" 제안.
"""
import os
from typing import Any
from src.state.schema import ShoppingState
from src.tools.meta_mcp_client import search_products as meta_search
from src.utils.agent_logger import agent_logger

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
    "아보카도": "kurly", "블루베리": "kurly", "두부": "kurly",
    "달걀": "kurly", "계란": "kurly", "식재료": "kurly", "신선": "kurly",
    "화장품": "oliveyoung", "뷰티": "oliveyoung",
    "패션": "musinsa", "의류": "musinsa", "신발": "musinsa",
}

# naver/coupang 검색 후 kurly를 제안할 신선식품/육류 키워드
_KURLY_SUGGEST_KEYWORDS = {
    "삼겹", "우삼겹", "소고기", "돼지", "닭", "계란", "생선", "해산물",
    "갈비", "등심", "안심", "차돌", "불고기", "수육", "삼겹살", "육류",
    "두부", "버섯", "콩나물", "시금치", "신선", "식재료", "고기",
}


def _env_true(name: str) -> bool:
    """문자열 환경변수를 bool 플래그처럼 해석한다."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _kurly_mvp_mode() -> bool:
    """실제 브라우저 MVP에서는 자동화 가능한 컬리만 주문 후보로 사용한다."""
    return _env_true("USE_REAL_BROWSER") or os.environ.get("MVP_MODE", "").strip().lower() == "kurly"


def _select_platforms(state: ShoppingState, recommendation_context: dict) -> list[str]:
    """플랫폼 선택 우선순위 로직."""
    override = state.get("override_platform")
    if override:
        return [override]

    if state.get("stage") == "cart_shopping":
        current = state.get("selected_platform")
        if current and current != "multi":
            return [current]

    target = state.get("target_platforms") or []
    if target:
        return target

    if _kurly_mvp_mode():
        return ["kurly"]

    pref = recommendation_context.get("preference_memory", {})
    platform_pattern = pref.get("platform_pattern", {})
    keywords = state.get("keywords") or []
    for kw in keywords:
        matched = platform_pattern.get(kw)
        if matched:
            return [matched]

    for kw in keywords:
        for kw_key, platform in PLATFORM_DEFAULTS_BY_KEYWORD.items():
            if kw_key in kw.lower():
                return [platform]

    condition = state.get("condition")
    if condition and condition in PLATFORM_DEFAULTS_BY_CONDITION:
        return PLATFORM_DEFAULTS_BY_CONDITION[condition]

    tried = state.get("tried_platforms") or []
    defaults = [p for p in ["naver", "coupang"] if p not in tried]
    return defaults if defaults else ["naver"]


def _should_suggest_kurly_early(keywords: list[str], tried_platforms: list[str]) -> bool:
    """검색 전, 키워드만 보고 컬리 제안 여부 판단."""
    if "kurly" in tried_platforms:
        return False
    return any(
        any(food_kw in kw.lower() for food_kw in _KURLY_SUGGEST_KEYWORDS)
        for kw in keywords
    )


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


def platform_agent_node(state: ShoppingState) -> dict:
    """
    Platform Agent.
    역할: 플랫폼 선택 + search_product() → search_results 갱신.
    추천/결제는 하지 않는다.
    """
    recommendation_context = state.get("recommendation_context") or {}
    keywords = state.get("keywords") or []
    exclude_keywords = state.get("exclude_keywords") or []
    condition = state.get("condition")
    tried_platforms = list(state.get("tried_platforms") or [])
    pending_action = state.get("pending_action") or {}
    intent = state.get("intent")

    if not keywords or all(k in ["그거", "저번에", "그것", "저것"] for k in keywords):
        return {
            "search_results": [],
            "stage": "idle",
            "error": "invalid_keywords",
            "last_agent": "platform_agent",
        }

    # ── 신선식품 키워드 감지 → 검색 없이 바로 컬리 제안 ──
    if (
        not _kurly_mvp_mode()
        and pending_action.get("type") != "platform_suggest"
        and _should_suggest_kurly_early(keywords, tried_platforms)
    ):
        result = {
            "tried_platforms": list(set(tried_platforms + ["kurly"])),
            "target_platforms": [],
            "search_results": [],
            "stage": "product_confirming",
            "error": None,
            "last_agent": "platform_agent",
            "pending_action": {
                "type": "platform_suggest",
                "message": "컬리에서 찾아볼까요?",
                "payload": {"target_platform": "kurly"},
            },
        }
        agent_logger.log_platform_agent(
            {"keywords": keywords, "intent": intent, "tried_platforms": tried_platforms, "trigger": "kurly_early_suggest"},
            result,
        )
        return result

    # ── 컬리 제안 수락/거절 처리 ──
    if pending_action.get("type") == "platform_suggest" and intent == "confirm":
        target = pending_action.get("payload", {}).get("target_platform", "kurly")
        selected_platforms = [target]
    elif pending_action.get("type") == "platform_suggest" and intent in ("deny", "next"):
        # 컬리 거절 → 네이버/쿠팡 검색
        selected_platforms = [p for p in ["naver", "coupang"] if p not in tried_platforms] or ["naver"]
    else:
        selected_platforms = _select_platforms(state, recommendation_context)

    sort_used = CONDITION_MAP.get(condition, "relevance") if condition else "relevance"
    query = " ".join(keywords)

    raw_results = meta_search(
        query=query,
        platforms=selected_platforms,
        condition=sort_used,
    )

    search_results = _filter_results(raw_results, exclude_keywords)
    tried_platforms = list(set(tried_platforms + selected_platforms))

    base = {
        "tried_platforms": tried_platforms,
        "selected_platform": selected_platforms[0] if len(selected_platforms) == 1 else "multi",
        "error": None,
        "last_agent": "platform_agent",
        "target_platforms": [],
        "pending_action": None,
        # 새 상품 탐색 시작 — 이전 상품 관련 필드 초기화
        "selected_product": None,
        "product_url": None,
        "current_product_index": 0,
        "explanation": None,
        "highlight_specs": [],
        "scored_products": [],
        "recommended_products": [],
        "reorder_resolution": None,
    }

    if not search_results:
        result = {**base, "search_results": [], "stage": "idle", "error": "no_results"}
    else:
        result = {**base, "search_results": search_results, "stage": "searching"}

    agent_logger.log_platform_agent(
        {"keywords": keywords, "intent": intent, "tried_platforms": tried_platforms,
         "selected_platforms": selected_platforms, "query": query},
        result,
    )
    return result
