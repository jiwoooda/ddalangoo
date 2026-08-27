"""WON-22 Unit 0 — mock_search_product의 검색 실패 fallback(DEFAULT_PRODUCTS)
tool 경계 자체를 고정한다. fl-2026-08-27-006 참고: agent 레벨(product_agent_node)
에서는 지금 _matches_requested_keywords의 부수효과로 우연히 걸러지지만, tool은
어떤 검색어를 넣어도 표시 없는 placeholder("상품 A")를 100% 무조건 반환한다 —
그 부수효과에 기대지 않고 tool 자체가 placeholder임을 표시하거나(Unit 8) 아예
반환하지 않아야 한다. 이 테스트는 지금은 FAIL해야 정상이다(제품 코드는 아직
수정 안 함, Unit 8에서 고침).

주의(실 쿠팡 API 재확인, 2026-08-27): SEARCH_MODE=mcp(운영 기본값)로 같은
검색 실패 상황을 재현하면 mock_search_product 자체가 아예 호출되지 않아
error="no_candidates"로 정상 처리되고 "상품 A"는 절대 노출되지 않는다 —
즉 이 결함은 실사용자에게 영향을 주는 프로덕션 버그가 아니라, mock 모드로
로컬 개발/테스트할 때만 해당하는 test-infra 위생 문제다. 그래도 mock은
다른 Living Test/로컬 개발이 결정론적 검증을 위해 계속 의존하므로 고칠
가치는 있다 — 다만 우선순위를 "사용자가 겪는 버그"로 과대평가하지 말 것."""
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
