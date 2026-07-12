"""
Search Client — mock / mcp 두 모드를 명시적으로 선택한다 (암묵적 폴백 체인 아님).

- mode="mock": 내장 mock 데이터만 사용 (네이버/MCP 전혀 안 거침, 결정적 결과)
- mode="mcp":  meta_mcp_client를 통해 실제 검색 (쿠팡/네이버는 meta-mcp 경유,
               kurly는 실제 URL이 확보된 후보에 한해 webview로 배송정보까지 보강)

기본 mode는 SEARCH_MODE 환경변수(mock|mcp, 기본값 mock)로 결정된다.
플랫폼 에이전트에서 `search_products(query, platforms, condition)` 형태로 호출됨.
"""
import os
from typing import Any, Literal

from src.tools.mock_tools import mock_search_product

SearchMode = Literal["mock", "mcp"]

SORT_MAP = {
    "price_asc": "price_low",
    "price_desc": "price_high",
    "relevance": "sim",
    "popularity": "sim",
    "review_score": "sim",
    "delivery_fast": "sim",
    "free_shipping": "sim",
    "value": "sim",
}


def _default_search_mode() -> SearchMode:
    value = os.getenv("SEARCH_MODE", "mock").strip().lower()
    return "mcp" if value == "mcp" else "mock"


def search_products(
    query: str,
    platforms: list[str],
    condition: str = "relevance",
    budget_max: int | None = None,
    limit_per_platform: int = 10,
    preferred_platform: str | None = None,
    mode: SearchMode | None = None,
) -> list[dict[str, Any]]:
    """
    platform_agent에서 호출하는 단일 진입점.

    mode 미지정 시 SEARCH_MODE 환경변수(mock|mcp, 기본 mock)를 따른다.
    - mock: 내장 mock 데이터만 사용. preferred_platform 지정 시 해당 플랫폼에 +2 슬롯 추가.
    - mcp:  meta_mcp_client.search_products로 위임 (실제 검색 + kurly webview 배송정보 보강).
    """
    valid_platforms = [p for p in platforms if p in ("naver", "coupang", "kurly")]
    if not valid_platforms:
        valid_platforms = ["naver", "coupang"]

    resolved_mode = mode or _default_search_mode()

    if resolved_mode == "mcp":
        from src.tools.meta_mcp_client import search_products as _mcp_search_products
        results = _mcp_search_products(
            query=query,
            platforms=valid_platforms,
            condition=condition,
            budget_max=budget_max,
        )
        return results[: limit_per_platform * len(valid_platforms)]

    def _plat_limit(plat: str) -> int:
        return limit_per_platform + 2 if plat == preferred_platform else limit_per_platform

    results = mock_search_product(
        query=query,
        platforms=valid_platforms,
        condition=condition,
        budget_max=budget_max,
    )
    per_platform: dict[str, list] = {}
    for p in results:
        plat = p.get("platform", "")
        per_platform.setdefault(plat, []).append(p)
    return [p for plat, items in per_platform.items() for p in items[:_plat_limit(plat)]]
