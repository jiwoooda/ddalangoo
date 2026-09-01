"""Commerce/결제 응답 fact 추출 — 결정론적 (ADR-005).

payment_agent / response_agent / respond_node 가 지금까지 사용자에게 보낼
문구를 직접 만들던 자리를, 문구 대신 "fact 번들"로 표현하기 위한 순수 모듈.

    {"state_facts": [{"fact_type": ..., ...}], "awaiting": "<enum>"}

이 모듈은 fact 만 만든다 — 실제 문구 생성(Voice)과 노드 연결은 별도 Task.
LLM/IO/랜덤 없음: 같은 입력이면 항상 같은 번들.

WON-26(Task 1 §5)에서 발견된 5개 버그는 원위치(payment/node.py 등)에서
"고치지" 않는다. 다만 fact 를 안전한 값으로 만들기 위한 정규화(Task 1 §3-E)와
delivery 규칙 단일화(§3-D)는 이 추출 단계에서 적용한다 — 이건 버그 수정이
아니라 "fact 를 안전하게 만드는 정규화"라 Task 2 스코프에 포함된다.
"""
from __future__ import annotations

import re
from typing import Any, Optional

__all__ = [
    # state fact 빌더
    "cart_contents", "single_item", "cart_empty", "item_just_added",
    "address_on_file", "address_selected", "no_address_on_file",
    "payment_method", "payment_method_fixed_no_registration",
    "delivery_estimate", "order_placed",
    "payment_error", "payment_error_from_exc",
    "selection_rechecking", "no_product_to_pay",
    "cart_cleared", "cancel_empties_cart", "cancel_available",
    "order_action_out_of_scope", "unanswerable",
    # 조립 / 파생
    "build_bundle", "derive_awaiting",
    "AWAITING_VALUES", "AWAITING_UNKNOWN",
]

# ══════════════════════════════════════════════════════════════════════════
# 값 정규화 (Task 1 §3-E)
# ══════════════════════════════════════════════════════════════════════════

_KR_NUMBERS = {
    "하나": 1, "한": 1, "일": 1, "둘": 2, "두": 2, "셋": 3, "세": 3,
    "넷": 4, "네": 4, "다섯": 5, "오": 5, "여섯": 6, "육": 6,
    "일곱": 7, "칠": 7, "여덟": 8, "팔": 8, "아홉": 9, "구": 9, "열": 10, "십": 10,
}


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if value is None:
        return default
    m = re.search(r"-?\d+", str(value).replace(",", ""))
    return int(m.group()) if m else default


def _coerce_positive_int(value: Any, default: int = 1) -> int:
    """payment/node.py::_coerce_positive_int 과 같은 규칙(숫자/한글수사).
    Task 3 에서 통일하기 전까지 의도적으로 복제 — fact 레벨에서 quantity 가
    None/0/음수로 새는 걸(WON-26 §5-2) 막는 안전 정규화이지 원위치 버그
    수정이 아니다."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value > 0 else default
    if value is None:
        return default
    text = str(value).strip()
    m = re.search(r"\d+", text.replace(",", ""))
    if m:
        n = int(m.group())
        return n if n > 0 else default
    for token, number in sorted(_KR_NUMBERS.items(), key=lambda x: -len(x[0])):
        if token in text:
            return number
    return default


def _label(keywords: Optional[list], product_name: Optional[str] = None) -> str:
    """keywords[0] → product_name → "상품" 순 폴백 (Task 1 §3-E)."""
    for kw in (keywords or []):
        if kw:
            return str(kw)
    if product_name:
        return str(product_name)
    return "상품"


def _format_address(address: Optional[dict]) -> str:
    a = address or {}
    line1 = str(a.get("address_line1") or "").strip()
    line2 = str(a.get("address_line2") or "").strip()
    return f"{line1} {line2}".strip() if line2 else line1


def _short_address(addr: str) -> str:
    parts = (addr or "").split()
    return " ".join(parts[:3]) + "..." if len(parts) > 3 else (addr or "")


# ══════════════════════════════════════════════════════════════════════════
# delivery timing 단일 규칙 (Task 1 §3-D / WON-26 §5-1)
# _delivery_msg 와 _describe_delivery 의 규칙 불일치를 여기서 하나로 통일한다.
# ══════════════════════════════════════════════════════════════════════════

_DELIVERY_TIMING_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("샛별", "새벽"), "next_morning_7am"),
    (("로켓",),        "next_day"),
    (("당일",),        "same_day"),
    (("2일",),         "two_days"),
)


def _delivery_timing(delivery_info: Optional[str]) -> tuple[str, Optional[str]]:
    text = str(delivery_info or "").strip()
    if not text:
        return "unknown", None
    for needles, timing in _DELIVERY_TIMING_RULES:
        if any(n in text for n in needles):
            return timing, None
    return "unknown", text


# ══════════════════════════════════════════════════════════════════════════
# state fact 빌더 (Task 1 §3-A) — 전부 순수 함수, dict 반환
# ══════════════════════════════════════════════════════════════════════════

def cart_contents(cart: Optional[list]) -> dict:
    rows = cart or []
    items = [
        {
            "label": _label(row.get("keywords"), row.get("product_name")),
            "quantity": _coerce_positive_int(row.get("quantity"), 1),
        }
        for row in rows
    ]
    return {
        "fact_type": "cart_contents",
        "items": items,
        "item_count": len(items),
        "total_krw": sum(_coerce_int(row.get("total"), 0) for row in rows),
    }


def single_item(keywords: Optional[list], product_name: Optional[str],
                quantity: Any, price: Any) -> dict:
    q = _coerce_positive_int(quantity, 1)
    return {
        "fact_type": "single_item",
        "label": _label(keywords, product_name),
        "quantity": q,
        "total_krw": _coerce_int(price, 0) * q,
    }


def cart_empty() -> dict:
    return {"fact_type": "cart_empty"}


def item_just_added(keywords: Optional[list], product_name: Optional[str],
                    quantity: Any) -> dict:
    return {
        "fact_type": "item_just_added",
        "label": _label(keywords, product_name),
        "quantity": _coerce_positive_int(quantity, 1),
    }


def no_address_on_file() -> dict:
    return {"fact_type": "no_address_on_file"}


def address_on_file(address: Optional[dict]) -> dict:
    """빈 주소면 no_address_on_file 로 전환 (Task 1 §3-E — 빈 주소 표시 금지)."""
    formatted = _format_address(address)
    if not formatted:
        return no_address_on_file()
    return {"fact_type": "address_on_file", "address": formatted}


def address_selected(address: Optional[dict]) -> dict:
    formatted = _format_address(address)
    if not formatted:
        return no_address_on_file()
    return {"fact_type": "address_selected", "address": _short_address(formatted)}


def payment_method() -> dict:
    """이 시스템이 지원하는 결제수단은 네이버페이 하나 — 표기 통일은 fact
    레벨에서 이미 해결(WON-26 §5-4). 문구 표기 변주는 Voice 모듈 책임."""
    return {"fact_type": "payment_method", "method": "네이버페이"}


def payment_method_fixed_no_registration() -> dict:
    """WON-38 — "카드는 어떻게 등록해요?" 류 (topic=payment_method, type=procedure).
    mock 결제는 네이버페이 고정이고 카드 등록·변경 기능이 시스템 설계상 아예 없다
    (mock_place_order/MockPaymentRecord 근거) — "구현 안 함"이 아니라 그런 구조다.
    payment_method()("수단이 뭐냐")와 구분되는 fact: "네이버페이로만 되고, 등록/변경은
    저희가 못 도와드린다"를 정직하게 안내한다."""
    return {
        "fact_type": "payment_method_fixed_no_registration",
        "method": "네이버페이",
        "registration_supported": False,
    }


def delivery_estimate(delivery_info: Optional[str], delivery_fee: Any = None) -> dict:
    timing, raw = _delivery_timing(delivery_info)
    return {
        "fact_type": "delivery_estimate",
        "timing": timing,
        "raw_delivery_text": raw,
        "fee_krw": _coerce_int(delivery_fee, 0),  # None/0 → 0(무료)
    }


def order_placed(order_id: Any) -> dict:
    return {
        "fact_type": "order_placed",
        "order_id": str(order_id) if order_id is not None else "",
    }


_PAYMENT_ERROR_KINDS = ("idempotency_conflict", "execution_error")


def payment_error(kind: str) -> dict:
    """kind 로만 구분(WON-26 §5-5 / Task 1 발견 5) — 지금은 두 경우 문구가
    같아도 fact 레벨에서는 나눠 이후 분기 가능하게."""
    if kind not in _PAYMENT_ERROR_KINDS:
        kind = "execution_error"
    return {"fact_type": "payment_error", "kind": kind, "retryable": True}


def payment_error_from_exc(exc: BaseException) -> dict:
    is_idem = type(exc).__name__ == "IdempotencyConflictError"
    return payment_error("idempotency_conflict" if is_idem else "execution_error")


def selection_rechecking() -> dict:
    return {"fact_type": "selection_rechecking"}


def no_product_to_pay() -> dict:
    return {"fact_type": "no_product_to_pay"}


def cart_cleared(reason: str = "cancel") -> dict:
    return {"fact_type": "cart_cleared", "reason": reason}


def cancel_empties_cart() -> dict:
    return {"fact_type": "cancel_empties_cart"}


def cancel_available() -> dict:
    """WON-35 Unit 3 — 결제 확정 전(pending) "취소돼요?" 류 질문에 답할 근거.
    아직 주문이 나가지 않아 지금 말하면 바로 멈출 수 있다는 사실만 담는다.
    확정 후 취소·환불(WON-36)은 이 fact 의 범위가 아니다 — when 은 항상
    "before_confirm" 하나뿐이고, 확정 후 상태는 이 fact 를 만들지 않는다."""
    return {"fact_type": "cancel_available", "when": "before_confirm"}


def order_action_out_of_scope(platform: Optional[str] = None) -> dict:
    """WON-36 — 주문 확정 후/idle 에서 취소·환불 요청. DDALANGOO 는 third-party
    (쿠팡 등) 주문의 취소·환불을 조회·실행할 수단이 없다. unanswerable("근거 없음")
    과 구분되는 "권한/수단 없음" — 톤이 달라야 한다(사과+안내지, 되묻기 아님).
    LLM 자유생성 금지 대상이라 Voice 가 아니라 고정 템플릿으로만 문구화한다."""
    return {"fact_type": "order_action_out_of_scope", "platform": platform or None}


_UNANSWERABLE_TOPICS = ("payment_method", "delivery")


def unanswerable(topic_hint: Optional[str] = None) -> dict:
    """근거 fact 없음 — Voice 모듈이 "그건 답하기 어려워요"류로 새로 생성.
    원래 pending message 를 접두어로 붙이지 않는다(WON-26 §5-3)."""
    if topic_hint not in _UNANSWERABLE_TOPICS:
        topic_hint = None
    return {"fact_type": "unanswerable", "topic_hint": topic_hint}


# ══════════════════════════════════════════════════════════════════════════
# awaiting 파생 (Task 1 §3-B, 승인 C)
# ══════════════════════════════════════════════════════════════════════════

AWAITING_VALUES = frozenset({
    "continue_or_pay", "cart_review", "payment_method_choice", "address_input",
    "address_confirm", "payment_password", "payment_retry", "what_to_buy",
    "order_complete", "selection_recheck", "cancel_confirm", "quantity", "none",
})
AWAITING_UNKNOWN = "unknown"

# 해당 노드가 자기 함수 안에서 직접 세팅해 그 흐름 안에서는 신뢰 가능한
# pending_action.type → awaiting 매핑. (last_agent=="cancel" 경로에서는 절대
# 참조하지 않는다 — §5-6: 그 값은 payment_confirm 으로 잘못 남는다.)
_BY_PENDING = {
    "continue_shopping": "continue_or_pay",
    "cart_review": "cart_review",
    "what_to_buy": "what_to_buy",
    "address_required": "address_input",
    "payment_method_confirm": "payment_method_choice",
    "payment_password": "payment_password",
    "payment_retry_confirm": "payment_retry",
    "payment_confirm": "order_complete",   # 정상 완료 경로에서만 도달(취소는 위에서 차단)
    "clarification": "selection_recheck",  # payment_agent Unit 9 실패 경로
}


def derive_awaiting(last_agent: Optional[str], stage: Optional[str],
                    pending_type: Optional[str] = None,
                    *, intent: Optional[str] = None) -> str:
    """`pending_action.type` 를 1차 소스로 신뢰하지 않는다(승인 C).

    - last_agent == "cancel" → type 이 "payment_confirm" 으로 잘못 남음
      (WON-26 §5-6)이라 type 을 아예 참조하지 않는다.
    - 그 외에는 last_agent + stage 로 대분류하고, 그 노드가 자기 함수에서
      직접 세팅해 신뢰 가능한 pending_type 만 세부 단계 구분에 쓴다.
    - 매핑되는 조합이 없으면 AWAITING_UNKNOWN. respond_node 의 generic fallback
      중 N2("이 상품으로 주문할까요?") / N3("결제를 계속 진행할까요?") 는
      의도적으로 여기서 UNKNOWN 을 반환한다 — 정상 경로엔 이미 대응하는
      pending_type(product_confirm / payment sub-steps)이 있고, 이 두 지점은
      그게 유실됐을 때만 도달하는 비정상 폴백이라 fact 화 대상이 아니다
      (§3-C unanswerable 과 같은 정신). N1("몇 개 필요하세요?")만 quantity 로
      매핑한다.
    """
    la = last_agent or ""
    st = stage or ""
    pt = pending_type or ""

    # 1) 취소 실행 — pending_type 절대 신뢰 안 함
    if la == "cancel":
        return "none"

    # 2) 취소 확인 노드 — cancel_declined / cancel_confirm 는 이 노드가 직접
    #    세팅하므로 신뢰 가능(§5-6 버그는 cancel_node 한정)
    if la == "cancel_confirmation":
        return "none" if pt == "cancel_declined" else "cancel_confirm"

    # 3) 종결 stage — last_agent 무관, stage 로 판정
    if st == "completed":
        return "order_complete"
    if st == "failed":
        return "payment_retry"

    # 4) address_confirm 은 같은 type 이라도 맥락별로 3갈래
    if pt == "address_confirm":
        if st == "payment_processing":
            return "address_confirm"          # P15: 결제 흐름 — 실제로 주소 확인 대기
        if intent == "confirm":
            return "none"                     # N6: respond_node ack, pending 클리어
        if intent in ("deny", "address_change"):
            return "address_input"            # N7
        return "address_confirm"              # R2/R3: response_agent 가 방금 세팅(intent=ask)

    # 5) 결제 흐름 내 세부 단계 — 신뢰 가능한 pending_type 으로 구분
    if pt in _BY_PENDING:
        return _BY_PENDING[pt]

    # 6) N1 — product_confirming 에서 상품을 확정했는데 수량이 없어 "몇 개
    #    필요하세요?" 를 되묻는 상태. 수량이 있었으면 router 가 payment_agent
    #    로 보내 이 respond_node 폴백에 도달하지 않으므로, 이 조합은 곧
    #    "수량 대기" 를 뜻한다.
    if st == "product_confirming" and intent == "confirm":
        return "quantity"

    # N2/N3 는 위 docstring 대로 의도적으로 UNKNOWN (fact 화 대상 아님).
    return AWAITING_UNKNOWN


# ══════════════════════════════════════════════════════════════════════════
# 번들 조립 (Task 1 §D)
# ══════════════════════════════════════════════════════════════════════════

def build_bundle(awaiting: str, *state_facts: Optional[dict]) -> dict:
    return {
        "state_facts": [f for f in state_facts if f],
        "awaiting": awaiting,
    }
