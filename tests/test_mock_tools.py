"""WON-22 Unit 8 — mock_search_product의 검색 실패 fallback(DEFAULT_PRODUCTS)
tool 경계 자체를 고정한다. fl-2026-08-27-006 참고: agent 레벨(product_agent_node)
에서는 _matches_requested_keywords의 부수효과로 우연히 걸러졌지만(그 보호는
의도된 게 아니었음), tool은 검색 실패 시 표시 없는 placeholder("상품 A")를
무조건 반환하고 있었다.

Unit 8에서 고침: mock_search_product는 이제 검색 실패 시 빈 리스트를 반환
(DEFAULT_PRODUCTS 자동 주입 제거), DEFAULT_PRODUCTS 자체엔 is_placeholder=
True/source="fixture" 표시를 추가했다. 이 테스트는 이제 정상적으로 PASS한다."""
from src.tools.mock_tools import mock_search_product


def test_no_match_search_does_not_return_unmarked_placeholder():
    results = mock_search_product("존재하지않는상상속상품명123", ["naver", "coupang", "kurly"])

    for product in results:
        assert product.get("is_placeholder") is True, (
            f"매치되는 카탈로그 상품이 없는데 표시 없는 fixture가 반환됨: "
            f"{product.get('product_name')!r}. mock_search_product의 DEFAULT_PRODUCTS "
            f"fallback은 반드시 is_placeholder=True로 표시하거나(Unit 8), 아예 "
            f"빈 리스트를 반환해야 한다."
        )


def test_no_match_search_returns_empty_list():
    """Unit 8 완료 조건: 검색 실패 시 아무 표시 없는 fixture가 섞여 나오는 게
    아니라 아예 빈 리스트여야 한다(product_agent가 이걸 그대로 error=
    "no_candidates"로 처리)."""
    results = mock_search_product("존재하지않는상상속상품명123", ["naver", "coupang", "kurly"])
    assert results == []


def test_default_products_are_marked_as_placeholder():
    """DEFAULT_PRODUCTS는 더 이상 자동으로 안 쓰이지만, 명시적으로 import해서
    쓰는 테스트를 위해 표시는 유지돼야 한다(운영/테스트 데이터 경로 분리)."""
    from src.tools.mock_tools import DEFAULT_PRODUCTS
    assert DEFAULT_PRODUCTS
    for product in DEFAULT_PRODUCTS:
        assert product.get("is_placeholder") is True
        assert product.get("source") == "fixture"
