"""WON-22 Unit 7 — 대체품 동의 파싱(결정론적)과 제안 가능 항목 계산을 고정.
"동의 범위 외 조건은 계속 유지"가 완료 조건이라 여기서 잘못 넓히면 이 Unit의
안전 목적이 깨진다 — LLM이 아니라 규칙으로 판정하는 이유가 이것."""
from src.agents.intent_agent import _parse_substitution_consent
from src.agents.product_agent import _offerable_substitution_fields, _substitution_offer_message


def test_size_only_mention_grants_only_specifics():
    granted = _parse_substitution_consent("다른 용량은 괜찮아", ["specifics", "brand"])
    assert granted == ["specifics"]


def test_brand_only_mention_grants_only_brand():
    granted = _parse_substitution_consent("다른 브랜드도 괜찮아", ["specifics", "brand"])
    assert granted == ["brand"]


def test_bare_agreement_grants_everything_offered():
    granted = _parse_substitution_consent("네 좋아요", ["specifics", "brand"])
    assert granted == ["specifics", "brand"]


def test_mention_not_in_offered_fields_is_ignored():
    # brand가애초에 제안 목록에 없으면(예: match_mode=brand라 specifics만 제안됨)
    # "브랜드"를 언급해도 offered_fields 밖이라 인정 안 됨
    granted = _parse_substitution_consent("브랜드도 괜찮아", ["specifics"])
    assert granted == []


def test_offerable_fields_exclude_already_granted():
    pr = {"match_mode": "exact_product", "substitution_scope": ["specifics"]}
    assert _offerable_substitution_fields(pr) == ["brand"]


def test_offerable_fields_empty_when_fully_granted():
    pr = {"match_mode": "exact_product", "substitution_scope": ["specifics", "brand"]}
    assert _offerable_substitution_fields(pr) == []


def test_offerable_fields_brand_mode_only_offers_brand():
    pr = {"match_mode": "brand", "substitution_scope": []}
    assert _offerable_substitution_fields(pr) == ["brand"]


def test_offerable_fields_category_mode_offers_nothing():
    pr = {"match_mode": "category", "substitution_scope": []}
    assert _offerable_substitution_fields(pr) == []


def test_offer_message_mentions_both_options():
    pr = {"brand": "서울우유", "variant": "나100%", "size": "1L"}
    msg = _substitution_offer_message(pr, ["specifics", "brand"])
    assert "서울우유 나100% 1L" in msg
    assert "다른 용량" in msg
    assert "다른 브랜드" in msg
