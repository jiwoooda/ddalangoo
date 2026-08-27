"""WON-22 Unit 3 — Product Identity 정규화 모듈(결정론적 핵심)의 브랜드·제품명·
용량별 테스트. LLM을 쓰지 않는 순수 함수라 tests/test_search_keywords.py와 같은
패턴으로 pytest만으로 충분하다. resolve_brand_ambiguity_llm(LLM 보조 함수)은
여기 포함하지 않는다 — scratchpad 직접 실행으로 확인, Unit 4/5가 실제로 연결할
때 Living Test로 커버."""
from src.utils.product_identity import (
    SizeValue,
    ProductIdentity,
    parse_size,
    parse_pack_count,
    normalize_brand,
    brand_appears_in,
    build_identity_from_candidate,
    build_identity_from_request,
    compare_identities,
)


# ── 단위 환산 동치 — 이 모듈의 존재 이유 ─────────────────────────

def test_liter_and_milliliter_are_equivalent():
    assert parse_size("1L") == parse_size("1000ml")


def test_kilogram_and_gram_are_equivalent():
    assert parse_size("1kg") == parse_size("1000g")


def test_different_amounts_are_not_equivalent():
    assert parse_size("1L") != parse_size("500ml")


def test_volume_and_weight_are_never_equal_even_with_same_number():
    assert parse_size("1000ml") != parse_size("1000g")


def test_real_coupang_product_names_parse_correctly():
    # WON-22 Unit 0에서 실제 쿠팡 검색으로 수집한 진짜 상품명들
    assert parse_size("서울우유 나100% 1등급 A 2300mL 2개 대용량 흰우유") == SizeValue(2300.0, "volume")
    assert parse_size("서울우유 나100% 1000ml") == SizeValue(1000.0, "volume")
    assert parse_size("서울우유 멸균 흰우유, 200ml, 48개") == SizeValue(200.0, "volume")


def test_no_size_mentioned_returns_none():
    assert parse_size("그냥 계란") is None
    assert parse_size("") is None


def test_comma_formatted_amount():
    assert parse_size("2,300mL") == SizeValue(2300.0, "volume")


# ── pack_count — 구매 수량과 별개 개념 ──────────────────────────

def test_pack_count_extracted_separately_from_size():
    size = parse_size("서울우유 멸균 흰우유, 200ml, 48개")
    count = parse_pack_count("서울우유 멸균 흰우유, 200ml, 48개")
    assert size == SizeValue(200.0, "volume")
    assert count == 48


def test_pack_count_handles_egg_carton_count():
    assert parse_pack_count("동물복지 계란 15구") == 15


def test_pack_count_none_when_absent():
    assert parse_pack_count("서울우유 1L") is None


# ── 브랜드 정규화 ────────────────────────────────────────────

def test_brand_normalization_ignores_whitespace_and_case():
    assert normalize_brand("서울우유") == normalize_brand(" 서울 우유 ")
    assert normalize_brand("CJ") == normalize_brand("cj")


def test_brand_appears_in_real_candidate_name():
    assert brand_appears_in("서울우유 나100% 1등급 A 2300mL 2개 대용량 흰우유", "서울우유") is True


def test_brand_appears_in_rejects_wrong_brand():
    assert brand_appears_in("남양 맛있는우유 GT 1L", "서울우유") is False


def test_brand_appears_in_tolerates_spacing_difference():
    assert brand_appears_in("서울 우유 1L 특가", "서울우유") is True


def test_brand_appears_in_passes_when_no_brand_requested():
    assert brand_appears_in("아무 상품이나", None) is True


# ── ProductIdentity 조립 ─────────────────────────────────────

def test_build_identity_from_request_normalizes_size():
    identity = build_identity_from_request({"brand": "서울우유", "size": "1L", "variant": "나100%"})
    assert identity.normalized_brand == "서울우유"
    assert identity.size == SizeValue(1000.0, "volume")
    assert identity.variant == "나100%"


def test_build_identity_from_candidate_parses_free_text():
    identity = build_identity_from_candidate({"product_name": "서울우유 나100% 1000ml", "brand": None})
    assert identity.size == SizeValue(1000.0, "volume")
    assert identity.normalized_brand == ""  # brand 필드가 없으면 빈 문자열(product_name 원문으로 별도 검증)


# ── compare_identities — "문자열 포함 여부만으로 exact match 안 함" ──

def test_compare_identities_matches_despite_different_size_notation():
    # 요청은 "1L", 실제 후보는 "1000ml" 표기 — 문자열은 다르지만 같은 값
    identity = build_identity_from_request({"brand": "서울우유", "size": "1L"})
    result = compare_identities(identity, "서울우유 나100% 1000ml")
    assert result.matches is True
    assert result.mismatches == []


def test_compare_identities_flags_wrong_brand():
    identity = build_identity_from_request({"brand": "서울우유"})
    result = compare_identities(identity, "남양 맛있는우유 GT 1L")
    assert result.matches is False
    assert any("brand_mismatch" in m for m in result.mismatches)


def test_compare_identities_flags_wrong_size():
    identity = build_identity_from_request({"brand": "서울우유", "size": "1L"})
    result = compare_identities(identity, "서울우유 나100% 500ml")
    assert result.matches is False
    assert any("size_mismatch" in m for m in result.mismatches)


def test_compare_identities_ignores_size_when_not_requested():
    identity = build_identity_from_request({"brand": "서울우유"})
    result = compare_identities(identity, "서울우유 1L")
    assert result.matches is True
