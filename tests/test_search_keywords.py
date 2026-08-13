from src.utils.search_keywords import build_search_query, normalize_search_keywords


def test_quantity_variants_collapse_to_product_name():
    assert normalize_search_keywords(["계란", "한 판", "계란 한 판"]) == ["계란"]
    assert build_search_query(["계란", "한 판", "계란 한 판"]) == "계란"


def test_common_spelling_aliases_are_not_concatenated():
    assert build_search_query(["분홍 소시지", "분홍 소세지"]) == "분홍 소시지"


def test_distinct_product_attributes_are_preserved():
    assert build_search_query(["브라질산", "커피 원두"]) == "브라질산 커피 원두"
