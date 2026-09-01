"""WON-20 Unit 1 — classify_scope 의 (scope, goal_shift) 판단 고정.

WON-39 실측 30개 발화(목적전환 10 / 스몰토크 10 / 쇼핑 내 애매 10)를 그대로
회귀로 박는다. 이 함수는 scope/goal_shift 만 판단하고 행동은 정하지 않는다.
아직 어떤 노드에도 연결되지 않았다 — 순수 계산만 검증(순수 추가).

Phase 1 설계 원칙: high-confidence out_of_scope 만 명확히 잡고, 애매하면
in_scope 로 기본값(WON-39 에서 "잘못된 리셋(FP) 0건" 이었던 안전 상태 유지).
"""
import pytest

from src.utils.scope_classifier import classify_scope as clf


# ── WON-39 회귀 30개 ────────────────────────────────────────────────────

# 목적전환 10개 → out_of_scope + goal_shift=True
GOAL_SHIFT = [
    "인터넷 좀 켜줘",
    "TV 소리 줄여줘",
    "아들한테 전화 걸어줘",
    "라디오 틀어줘",
    "에어컨 꺼줘",
    "거실 불 켜줘",
    "며느리한테 문자 보내줘",
    "전세가 나을까 월세가 나을까",
    "이 근처 부동산 시세 좀 비교해줘",
    "대출 상담 좀 받고 싶은데",
]

# 스몰토크 10개 → bridgeable + goal_shift=False (쇼핑 문맥 유지)
SMALLTALK = [
    "아이고 힘드네",
    "오늘 날씨가 왜 이렇대",
    "손주가 보고 싶네",
    "요즘 무릎이 영 시원찮아",
    "날이 추워지니까 으슬으슬하네",
    "밥맛이 통 없어",
    "이번 명절엔 애들이 다 온다는구먼",
    "허리가 아파서 앉아 있기가 힘들어",
    "혼자 있으니까 적적하네",
    "잠이 통 안 와",
]

# 쇼핑 내 애매 10개 → in_scope + goal_shift=False
SHOPPING_AMBIGUOUS = [
    "아까 그거 말고 다른 거",
    "다른 거 보여줘",
    "그거 말고",
    "좀 더 싼 거 없나",
    "이건 별로인데",
    "다시 보여줘봐",
    "아까 그거 뭐였지",
    "그중에 두 번째 거",
    "좀 더 큰 걸로",
    "그냥 아무거나 괜찮은 걸로",
]


@pytest.mark.parametrize("text", GOAL_SHIFT)
def test_goal_shift_utterances(text):
    assert clf(text, {}) == {"scope": "out_of_scope", "goal_shift": True}, text


@pytest.mark.parametrize("text", SMALLTALK)
def test_smalltalk_is_bridgeable(text):
    assert clf(text, {}) == {"scope": "bridgeable", "goal_shift": False}, text


@pytest.mark.parametrize("text", SHOPPING_AMBIGUOUS)
def test_shopping_ambiguous_stays_in_scope(text):
    assert clf(text, {}) == {"scope": "in_scope", "goal_shift": False}, text


# ── 반환 형태 ──────────────────────────────────────────────────────────

def test_return_shape():
    got = clf("우유 담아줘", {})
    assert set(got.keys()) == {"scope", "goal_shift"}
    assert got["scope"] in {"in_scope", "bridgeable", "out_of_scope"}
    assert isinstance(got["goal_shift"], bool)


def test_goal_shift_true_iff_out_of_scope():
    """goal_shift 는 out_of_scope 일 때만 True."""
    for text in GOAL_SHIFT:
        assert clf(text, {})["goal_shift"] is True
    for text in SMALLTALK + SHOPPING_AMBIGUOUS:
        assert clf(text, {})["goal_shift"] is False


# ── Phase 1 보수성: 애매하면 in_scope, 절대 out_of_scope 로 기본값 금지 ──

@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_defaults_in_scope(text):
    assert clf(text, {}) == {"scope": "in_scope", "goal_shift": False}


@pytest.mark.parametrize("text", [
    "그거 담아줘",
    "이거 얼마야",
    "장바구니 보여줘",
    "결제할게",
    "좀 더 저렴한 걸로 바꿔줘",
    "방금 그 상품 다시",
])
def test_plain_shopping_never_out_of_scope(text):
    got = clf(text, {})
    assert got["scope"] != "out_of_scope", text
    assert got["goal_shift"] is False, text


def test_device_noun_without_control_verb_is_not_goal_shift():
    """'TV 받침대 사줘' 처럼 가전 '명사'만 있고 제어 '동사'가 없으면
    목적전환이 아니다 — 보수적으로 in_scope 유지(오리셋 방지)."""
    for text in ("TV 받침대 사줘", "라디오 사려고 하는데", "에어컨 필터 있어?"):
        assert clf(text, {})["scope"] != "out_of_scope", text


def test_context_arg_is_accepted_and_optional():
    """context 는 받되 Phase 1 로직엔 쓰지 않는다 — 넘겨도/생략해도 동일."""
    assert clf("에어컨 꺼줘", {}) == clf("에어컨 꺼줘", {"stage": "browsing"})
    assert clf("다른 거 보여줘") == clf("다른 거 보여줘", {})


def test_context_defaults_to_none():
    assert clf("아이고 힘드네")["scope"] == "bridgeable"
