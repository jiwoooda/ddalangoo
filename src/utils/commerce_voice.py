"""Commerce/결제 문구 생성 — fact 번들 → 어르신 친화 안내 문장 1개 (Task 3).

    render_voice({"state_facts": [...], "awaiting": "<enum>"}) -> str

파이프라인:
    fact 번들 (commerce_facts.py) → [LLM: 자연스러운 문구] → reflection 검증
      → 실패/불가 시 결정론적 폴백 템플릿

설계 결정(승인):
- 모델: get_llm("context", ...) — profile_topup/satisfaction_checkin 과 동일 티어.
- reflection 실패 시 Haiku 재생성 없이 바로 폴백 (결제 문구는 짧고, 폴백은
  이미 검증된 안전 문구).
- 반환은 str 하나. degraded 여부는 이 모듈이 agent_logger 로 직접 남긴다 —
  호출부(payment/node.py)는 알 필요 없음.
- persona 는 호출부가 넘기지 않고 여기서 SMALLTALK_CHARACTER 를 직접 참조.

스코프(Task 3):
- payment/node.py 의 in-scope 지점만 이 모듈로 교체한다.
- WON-29 가 이미 재작성한 지점(P14 no_address / P15 address_selected 결제흐름 /
  P22 fallback 가드)은 배선 대상이 아니다. 폴백 템플릿은 그 awaiting 값
  (address_input/address_confirm)도 커버하지만 호출부만 안 붙인다.
- response_agent.py / respond_node 는 Task 4.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from langchain_core.messages import HumanMessage

from configs.llm_config import get_llm
from src.prompts.smalltalk_prompt import SMALLTALK_CHARACTER
from src.prompts.voice_prompt import VOICE_PROMPT
from src.utils.agent_logger import agent_logger
from src.utils.retry import classify_failure, retry_call

__all__ = ["render_voice"]

# response_agent._reflect_elderly 와 동일 규칙 — util → agent 역방향 import 를
# 피하려고 의도적으로 복제한다(commerce_facts._coerce_positive_int 복제와 같은
# 선례). 어르신 친화 검증 로직 통일은 별도 작업에서.
_ELDERLY_FORBIDDEN = ["플랫폼", "최저가", "가성비", "혜택", "할인율", "할인가", "프로모션", "할인"]
_MAX_SENTENCE_LEN = 35


def _reflect_elderly(text: str) -> tuple[bool, str]:
    sentences = [s.strip() for s in text.split(".") if s.strip()]
    if len(sentences) > 3:
        return False, f"문장 수 과다({len(sentences)}개)"
    for s in sentences:
        if len(s) > _MAX_SENTENCE_LEN:
            return False, f"긴 문장({len(s)}자): {s[:20]}..."
    found = [w for w in _ELDERLY_FORBIDDEN if w in text]
    if found:
        return False, f"어려운 단어 포함: {', '.join(found)}"
    return True, ""


# ── LLM 경로 ─────────────────────────────────────────────────────────────

_llm_cache: dict[float, Any] = {}


def _get_llm(timeout: float = 2.5):
    llm = _llm_cache.get(timeout)
    if llm is None:
        llm = get_llm(
            "context", temperature=0.3, max_tokens=150,
            retry_owner="application", timeout=timeout,
        )
        _llm_cache[timeout] = llm
    return llm


def _try_llm(bundle: dict, timeout: float) -> Optional[str]:
    """LLM 으로 문구 생성. 실패(예외/빈 응답)면 None."""
    try:
        raw = retry_call(
            _get_llm(timeout).invoke,
            [HumanMessage(content=VOICE_PROMPT.format(
                persona=SMALLTALK_CHARACTER,
                bundle_json=json.dumps(bundle, ensure_ascii=False),
                awaiting=bundle.get("awaiting", "unknown"),
            ))],
        ).content.strip()
    except Exception as e:  # noqa: BLE001 — 분류는 아래 로그로만
        agent_logger.log(f"[commerce_voice] LLM 생성 실패({classify_failure(e).value}): {e} → 폴백")
        return None
    return raw or None


def render_voice(bundle: dict, *, timeout: float = 2.5) -> str:
    """fact 번들 → 사용자에게 보여줄 안내 문장 하나."""
    text = _try_llm(bundle, timeout)
    if text:
        ok, reason = _reflect_elderly(text)
        if ok:
            return text
        agent_logger.log(f"[commerce_voice] reflection 실패({reason}) → 폴백")
    else:
        agent_logger.log_graceful_degradation(
            node="commerce_voice", reason="voice_llm_failed", stage="response_llm",
        )
    return _fallback(bundle)


# ══════════════════════════════════════════════════════════════════════════
# 결정론적 폴백 템플릿
# ══════════════════════════════════════════════════════════════════════════

def _facts_by_type(bundle: dict) -> dict[str, dict]:
    return {f.get("fact_type"): f for f in (bundle.get("state_facts") or []) if isinstance(f, dict)}


def _items_and_total(facts: dict) -> tuple[str, int]:
    cc = facts.get("cart_contents")
    if cc and cc.get("items"):
        summary = ", ".join(f"{it.get('label', '상품')} {it.get('quantity', 1)}개" for it in cc["items"])
        return summary, int(cc.get("total_krw") or 0)
    si = facts.get("single_item")
    if si:
        return f"{si.get('label', '상품')} {si.get('quantity', 1)}개", int(si.get("total_krw") or 0)
    return "", 0


_DELIVERY_PHRASE = {
    "next_morning_7am": "내일 아침 7시 전에 와요.",
    "next_day": "내일 와요.",
    "same_day": "오늘 와요.",
    "two_days": "이틀 뒤에 와요.",
}


def _describe_delivery(de: dict) -> str:
    phrase = _DELIVERY_PHRASE.get(de.get("timing"))
    if phrase:
        return phrase
    raw = de.get("raw_delivery_text")
    return f"{raw}(으)로 배송돼요." if raw else "배송 정보는 아직 확인 중이에요."


def _answer_line(facts: dict) -> str:
    """P2/P3/P4 — 결제 흐름 중 질문에 답하는 조각(대기 안내 앞에 붙는다).
    원래 pending 메시지를 접두어로 쓰지 않는다(WON-26 §5-3)."""
    if "unanswerable" in facts:
        return "그 부분은 정확히 안내해 드리기 어려워요."
    de = facts.get("delivery_estimate")
    if de and "order_placed" not in facts:
        return _describe_delivery(de)
    pm = facts.get("payment_method")
    if pm and "cart_contents" not in facts and "single_item" not in facts:
        return "네이버페이로만 결제할 수 있어요."
    return ""


def _fb_continue_or_pay(facts: dict) -> str:
    added = facts.get("item_just_added")
    cc = facts.get("cart_contents")
    if added and cc and int(cc.get("item_count") or 0) > 1:
        return f"{added.get('label', '상품')}도 담았어요. 총 {cc['item_count']}가지예요. 결제할까요, 더 담을까요?"
    if added:
        return f"{added.get('label', '상품')} {added.get('quantity', 1)}개 담았어요. 결제할까요, 더 보실래요?"
    return "장바구니에 담았어요. 결제할까요, 더 보실래요?"


def _fb_cart_review(facts: dict) -> str:
    if "cart_empty" in facts:
        return "장바구니가 비었어요. 더 담으실래요?"
    summary, total = _items_and_total(facts)
    if total:
        return f"총 {total:,}원이에요. 바꾸거나 뺄 게 있으면 말씀해 주세요."
    return "담으신 상품을 확인해 주세요."


def _fb_payment_method_choice(facts: dict) -> str:
    answer = _answer_line(facts)
    summary, total = _items_and_total(facts)
    if total:
        head = f"{summary}, 총 {total:,}원이에요." if summary else f"총 {total:,}원이에요."
        body = f"{head} 네이버로 결제할까요?"
    else:
        body = "네이버로 결제할까요?"
    return f"{answer} {body}".strip()


def _fb_payment_password(facts: dict) -> str:
    answer = _answer_line(facts)
    return f"{answer} 결제 비밀번호를 입력해 주시겠어요?".strip()


def _fb_payment_retry(facts: dict) -> str:
    return "결제 중에 문제가 있었어요. 다시 시도해 볼까요?"


def _fb_what_to_buy(facts: dict) -> str:
    return "무엇을 살지 먼저 알려주시겠어요?"


def _fb_order_complete(facts: dict) -> str:
    de = facts.get("delivery_estimate")
    suffix = f" {_DELIVERY_PHRASE[de['timing']]}" if de and de.get("timing") in _DELIVERY_PHRASE else ""
    if suffix:
        return f"주문이 완료됐어요!{suffix}"
    return "주문이 완료됐어요! 잘 접수됐어요."


def _fb_selection_recheck(facts: dict) -> str:
    return "상품 정보를 다시 확인하고 있어요. 잠시만요."


def _fb_cancel_confirm(facts: dict) -> str:
    return "정말 그만두시겠어요? 장바구니에 담긴 것도 비워져요."


def _fb_quantity(facts: dict) -> str:
    return "네, 몇 개 필요하세요?"


def _fb_none(facts: dict) -> str:
    if "cart_cleared" in facts or "cancel_empties_cart" in facts:
        return "구매를 그만두고 장바구니를 비웠어요."
    return "네, 알겠어요."


def _fb_address_input(facts: dict) -> str:
    return "배송지를 알려주시겠어요?"


def _fb_address_confirm(facts: dict) -> str:
    answer = _answer_line(facts)
    addr = (facts.get("address_selected") or facts.get("address_on_file") or {}).get("address")
    body = f"{addr}로 보내면 될까요?" if addr else "이 배송지로 보내면 될까요?"
    return f"{answer} {body}".strip()


def _fb_generic(facts: dict) -> str:
    return "무엇을 도와드릴까요?"


_FALLBACK_BUILDERS: dict[str, Callable[[dict], str]] = {
    "continue_or_pay": _fb_continue_or_pay,
    "cart_review": _fb_cart_review,
    "payment_method_choice": _fb_payment_method_choice,
    "payment_password": _fb_payment_password,
    "payment_retry": _fb_payment_retry,
    "what_to_buy": _fb_what_to_buy,
    "order_complete": _fb_order_complete,
    "selection_recheck": _fb_selection_recheck,
    "cancel_confirm": _fb_cancel_confirm,
    "quantity": _fb_quantity,
    "none": _fb_none,
    "address_input": _fb_address_input,
    "address_confirm": _fb_address_confirm,
}


def _fallback(bundle: dict) -> str:
    facts = _facts_by_type(bundle)
    builder = _FALLBACK_BUILDERS.get(bundle.get("awaiting", ""), _fb_generic)
    text = builder(facts).strip()
    return text or "무엇을 도와드릴까요?"
