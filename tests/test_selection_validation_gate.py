"""WON-22 Unit 9 — 최종 선택 검증 게이트. Unit 4가 선택 이전에 이미 같은
검사를 하지만, 이건 "실제로 반환된 결과 자체"를 독립적으로 재검증하는 마지막
안전판이라 별도로 테스트한다(완료 조건: "Product Agent가 잘못된 결과를 내도
사용자에게 노출되지 않음")."""
from unittest.mock import patch

import src.agents.product_agent as pa
from src.agents.product_agent import validate_selected_product, product_agent_node


_REQUEST = {"brand": "서울우유", "match_mode": "brand", "excluded_brands": []}


def test_matching_product_passes():
    result = validate_selected_product({"product_name": "서울우유 1L", "product_url": "https://a"}, _REQUEST)
    assert result.matches is True


def test_wrong_brand_fails():
    result = validate_selected_product({"product_name": "남양 맛있는우유 1L", "product_url": "https://a"}, _REQUEST)
    assert result.matches is False
    assert any("brand_mismatch" in m for m in result.mismatches)


def test_placeholder_fails_even_if_brand_matches():
    result = validate_selected_product(
        {"product_name": "서울우유 1L", "product_url": "https://a", "is_placeholder": True}, _REQUEST,
    )
    assert result.matches is False
    assert any("placeholder" in m for m in result.mismatches)


def test_missing_url_fails():
    result = validate_selected_product({"product_name": "서울우유 1L", "product_url": None}, _REQUEST)
    assert result.matches is False
    assert any("missing_url" in m for m in result.mismatches)


def test_excluded_brand_fails():
    request = {"brand": None, "match_mode": "category", "excluded_brands": ["서울우유"]}
    result = validate_selected_product({"product_name": "서울우유 1L", "product_url": "https://a"}, request)
    assert result.matches is False
    assert any("excluded_brand" in m for m in result.mismatches)


def test_no_product_request_passes_vacuously():
    result = validate_selected_product({"product_name": "아무거나", "product_url": "https://a"}, None)
    assert result.matches is True


def test_no_selected_product_fails():
    result = validate_selected_product(None, _REQUEST)
    assert result.matches is False


def test_gate_intercepts_when_internal_logic_slips_a_bad_selection():
    """방어선 증명: product_agent 내부 로직(_product_agent_node_impl)이 실수로
    조건 안 맞는 상품을 selected_product로 반환해도, 바깥 게이트(product_agent_
    node)가 이를 잡아 selection_validation_failed로 되돌리는지 확인한다."""
    bad_result = {
        "search_query": "서울우유",
        "stage": "searching",
        "selected_product": {"product_name": "남양 맛있는우유 1L", "product_url": "https://a"},
        "recommended_products": [],
        "current_product_index": 0,
        "error": None,
        "last_agent": "product_agent",
    }
    state = {
        "intent": "buy", "keywords": ["서울우유"], "exclude_keywords": [],
        "condition": None, "current_product_index": 0, "recommended_products": [],
        "recommendation_context": None, "quantity": 1,
        "product_request": {"category": "우유", "brand": "서울우유", "match_mode": "brand", "excluded_brands": []},
    }
    with patch.object(pa, "_product_agent_node_impl", return_value=bad_result):
        out = product_agent_node(state)

    assert out["error"] == "selection_validation_failed"
    assert out["selected_product"] is None
    assert out["pending_action"]["type"] == "clarification"


def test_gate_passes_through_good_selection_unchanged():
    good_result = {
        "search_query": "서울우유",
        "stage": "searching",
        "selected_product": {"product_name": "서울우유 1L", "product_url": "https://a"},
        "recommended_products": [{"product_name": "서울우유 1L", "product_url": "https://a"}],
        "current_product_index": 0,
        "error": None,
        "last_agent": "product_agent",
    }
    state = {
        "intent": "buy", "keywords": ["서울우유"], "exclude_keywords": [],
        "condition": None, "current_product_index": 0, "recommended_products": [],
        "recommendation_context": None, "quantity": 1,
        "product_request": {"category": "우유", "brand": "서울우유", "match_mode": "brand", "excluded_brands": []},
    }
    with patch.object(pa, "_product_agent_node_impl", return_value=good_result):
        out = product_agent_node(state)

    assert out is good_result
    assert out["error"] is None
