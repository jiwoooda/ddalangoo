"""WON-22 Unit 5 — ProductResolver의 4개 분기(0/1/동일identity 여러 개/
서로 다른 identity 여러 개)를 고정. Unit 4(enforce_hard_constraints)가 이미
브랜드/옵션/사이즈 하드 조건을 통과시킨 뒤 넘긴다는 전제이므로, 여기서는
그 이후 단계(개수에 따른 분기)만 검증한다."""
from src.agents.product_resolver import ProductResolver


def test_zero_candidates_is_not_found():
    result = ProductResolver.resolve({"brand": "서울우유", "match_mode": "exact_product"}, [])
    assert result.status == "not_found"
    assert result.selected is None


def test_single_candidate_is_selected_with_match_evidence():
    request = {"brand": "서울우유", "variant": "나100%", "size": "1L", "match_mode": "exact_product"}
    candidate = {"product_name": "서울우유 나100% 1000ml", "platform": "coupang"}
    result = ProductResolver.resolve(request, [candidate])
    assert result.status == "selected"
    assert result.selected == candidate
    assert result.match_evidence == {
        "match_mode": "exact_product",
        "requested_brand": "서울우유",
        "requested_variant": "나100%",
        "requested_size": "1L",
        "candidate_name": "서울우유 나100% 1000ml",
    }


def test_same_product_different_sellers_is_same_identity_multiple():
    # 이름이 완전히 동일한 상품을 서로 다른 판매처가 파는 경우 — 오퍼 비교 대상
    request = {"brand": "서울우유", "match_mode": "exact_product"}
    candidates = [
        {"product_name": "서울우유 나100% 1000ml", "platform": "coupang", "price": 3200},
        {"product_name": "서울우유 나100% 1000ml", "platform": "naver", "price": 3000},
    ]
    result = ProductResolver.resolve(request, candidates)
    assert result.status == "same_identity_multiple"
    assert result.selected is None
    assert result.candidates == candidates


def test_different_products_is_ambiguous():
    # Unit 4의 하드 필터는 통과했지만(브랜드/사이즈는 맞음) product_name 자체는
    # 서로 다른 두 상품 — 자동으로 아무거나 고르면 안 됨
    request = {"brand": "서울우유", "match_mode": "exact_product"}
    candidates = [
        {"product_name": "서울우유 1L 흰우유", "platform": "coupang"},
        {"product_name": "서울우유 목장의 신선함이 살아있는 우유 1L", "platform": "naver"},
    ]
    result = ProductResolver.resolve(request, candidates)
    assert result.status == "ambiguous"
    assert result.selected is None
