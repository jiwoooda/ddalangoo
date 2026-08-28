"""
Response Agent Node.

역할: 랭킹된 상품 → 노인 친화 자연어 설명 생성 / 상품 QA 답변.
(기존 product_agent Phase 2 분리)
"""
import json
import re
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from configs.llm_config import get_llm
from src.state.schema import ShoppingState
from src.state.node_inputs import ResponseAgentInput, ResponseAgentUpdate
from src.prompts.response_prompt import RESPONSE_EXPLAIN_PROMPT, RESPONSE_QA_PROMPT, RESPONSE_ADVICE_PROMPT
from src.utils.agent_logger import agent_logger
from src.utils.priority_resolver import _mentions_same_target
from src.utils.retry import classify_failure, retry_call
from src.agents.product_agent import _safety_fallback_keywords

_llm: BaseChatModel | None = None

# 어르신 친화 검증 — 이 단어가 나오면 Reflection 실패로 재생성
_ELDERLY_FORBIDDEN = ["플랫폼", "최저가", "가성비", "혜택", "할인율", "할인가", "프로모션"]
_MAX_SENTENCE_LEN = 35

# WON-23 Unit 3 — product_decision_advice는 카탈로그를 전혀 안 준 채 LLM에
# 묻는다. 그런데도 답변에 "12,900원이에요"처럼 가격으로 보이는 구체적 숫자가
# 나오면 100% 환각(우리가 준 적 없는 정보)이므로, 프롬프트 지시만 믿지 않고
# 코드로 한 번 더 걸러낸다(이 세션에서 반복된 패턴 — LLM 판단이 불안정한
# 곳은 결정론적 후처리로 최종 확인).
_PRICE_LIKE_PATTERN = re.compile(r"\d[\d,]*\s*원")
_ADVICE_FALLBACK_ANSWER = "지금은 정확히 답을 드리기 어려워요. 그래도 둘 다 좋은 선택이에요!"

# 상품 설명 끝에 LLM이 붙이는 CTA 문구 — pending_msg와 중복되므로 제거 대상
_CTA_ENDINGS = ("주문할까요?", "어떠세요?", "구매할까요?", "사드릴까요?", "주문해드릴까요?")

_ADDRESS_KEYWORDS = ("배송지", "주소", "배달지", "받는 곳", "배달 주소")


def _get_llm() -> BaseChatModel:
    global _llm
    if _llm is None:
        # retry_owner="application": 이 모델을 쓰는 호출부가 모두 retry_call()로
        # 감싸므로 SDK 자체 재시도는 꺼서 중첩 재시도를 막는다.
        _llm = get_llm("response", temperature=0, max_tokens=300, retry_owner="application")
    return _llm


def _reflect_elderly(text: str) -> tuple[bool, str]:
    """Reflection: 어르신 친화 출력 검증. (True, "") = 통과."""
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


def _reflect_no_catalog_claims(text: str) -> tuple[bool, str]:
    """WON-23 Unit 3 가드: 카탈로그를 안 준 조언 답변에 가격으로 보이는
    숫자가 나오면 환각으로 간주한다. (True, "") = 통과."""
    match = _PRICE_LIKE_PATTERN.search(text)
    if match:
        return False, f"가격으로 보이는 값 포함: {match.group()!r}"
    return True, ""


def _generate_advice_answer(user_input: str) -> tuple[str, bool, str, bool, bool]:
    """상품 결정 전 조언(WON-23 Unit 3) — 카탈로그 없이 일반 지식 기반
    답변만 생성한다. (answer, reflection_passed, reason, replaced, degraded)."""
    try:
        answer = retry_call(
            _get_llm().invoke, [HumanMessage(content=RESPONSE_ADVICE_PROMPT.format(user_input=user_input))]
        ).content.strip()
    except Exception as e:
        agent_logger.log(f"[response_agent] 조언 답변 생성 오류({classify_failure(e).value}): {e} → fallback")
        answer = ""

    if not answer:
        agent_logger.log_graceful_degradation(node="response_agent", reason="advice_llm_failed", stage="response_llm")
        return _ADVICE_FALLBACK_ANSWER, True, "", False, True

    ok, reason = _reflect_elderly(answer)
    replaced = False
    if not ok:
        agent_logger.log(f"[response_agent] Reflection 실패: {reason} → Haiku 재생성")
        agent_logger.log_quality_regeneration(node="response_agent", reason=reason)
        answer = _simplify_with_haiku(answer, reason)
        replaced = True

    # 카탈로그 미인용 가드는 Haiku 재생성 이후 결과에도 다시 확인한다 —
    # 단순화 과정에서 숫자가 살아남을 수 있음. 여기서 걸리면 Haiku로
    # 다시 손보지 않고 바로 안전한 고정 문구로 바꾼다: 이 가드는 "환각된
    # 사실"을 잡는 것이라, 문장만 다듬는 Haiku 재생성으로는 그 사실 자체가
    # 제거된다는 보장이 없다(길이/어휘 문제와 다른 성격).
    catalog_ok, catalog_reason = _reflect_no_catalog_claims(answer)
    if not catalog_ok:
        agent_logger.log(f"[response_agent] 카탈로그 미인용 가드 실패: {catalog_reason} → 안전 문구로 교체")
        agent_logger.log_quality_regeneration(node="response_agent", reason=catalog_reason)
        answer = _ADVICE_FALLBACK_ANSWER
        replaced = True
        ok = False
        reason = catalog_reason

    return answer, ok, reason, replaced, False


def _simplify_with_haiku(explanation: str, reason: str) -> str:
    """Reflection 실패 시 context 모델(Haiku)로 재생성(Recovery: 품질 재생성).
    LangSmith 자동 추적."""
    try:
        llm = get_llm("context", temperature=0, max_tokens=150, retry_owner="application")
        content = (
            f"다음 쇼핑 안내 문장을 70대 어르신이 이해하기 쉽게 고쳐주세요.\n"
            f"문제점: {reason}\n"
            f"원문: {explanation}\n\n"
            f"규칙: 2문장 이내 / 한 문장 15자 이내 / 쉬운 단어만 / 존댓말(~이에요, ~할까요?) / 텍스트만 반환"
        )
        result = retry_call(llm.invoke, [HumanMessage(content=content)])
        return result.content.strip()
    except Exception as e:
        agent_logger.log(f"[response_agent] Haiku 재생성 실패({classify_failure(e).value}): {e} → 원문 유지")
        return explanation


def _format_safety_substitution(preference_context: dict, keywords: list[str]) -> str | None:
    """건강/식이 제약 때문에 원 키워드 대신 구체 대체어(예: "우유"→"락토프리
    우유")로 찾은 경우, 설명 생성 LLM에 그 사유를 명시적으로 알려준다.
    이걸 안 넘기면 LLM이 axis_contributions만 보고 배송/가격 같은 부차적
    이유만 말하고, 정작 사용자에게 가장 중요한 "왜 이 상품이 안전한지"는
    설명에서 누락되는 문제가 있었다(실측: 유당불내증 프로필에 락토프리
    우유를 추천하면서 "로켓배송이라 빨라요"만 이유로 나감).

    exclude_additions/keyword_additions는 프로필 제약이 있으면 오늘 뭘
    사든 채워질 수 있어서(product_agent.py의 diet_query_additions와 동일한
    문제), 오늘 keywords가 그 제약의 위험군과 실제로 관련 있을 때만 노출
    한다 — 안 그러면 "사과 사줘"에 "유당불내증이 있으셔도 안심하고
    드실 수 있는 사과맛이에요" 같은 엉뚱한 안전 사유가 붙는다(실측 확인됨).
    """
    additions = (preference_context or {}).get("keyword_additions") or []
    exclusions = (preference_context or {}).get("exclude_additions") or []
    if not additions or not exclusions:
        return None
    relevant_exclusions = [
        ex for ex in exclusions
        if any(
            _mentions_same_target(kw, risk_term)
            for kw in keywords
            for risk_term in _safety_fallback_keywords(ex)
        )
    ]
    if not relevant_exclusions:
        return None
    return (
        f"주의: 건강/식이 제약({', '.join(relevant_exclusions)}) 때문에 "
        f"'{', '.join(additions)}'로 대체해서 찾은 상품입니다 — "
        f"추천 이유에 이 안전 대체 사실을 최우선으로 언급하세요."
    )


def _format_brand_mismatch_note(product: dict, keywords: list[str]) -> str | None:
    """사용자가 명시한 keyword 중 일부가 실제 선택된 상품의 이름/브랜드에 전혀
    없으면(예: "애플 우유" 요청에 애플과 무관한 "부산우유"가 선택된 경우), 그
    사실을 설명 LLM에 명시적으로 알려 사용자에게 먼저 고지하게 한다.

    product_agent._matches_requested_keywords는 keywords 중 하나만 맞아도
    후보를 통과시키므로(예: "우유"만 맞고 "애플"은 안 맞아도 통과), 그대로
    두면 요청을 완전히 만족한 것처럼 조용히 다른 상품을 보여주게 된다(실측
    확인: 스코어링 LLM 자체는 "애플과 무관"이라고 정확히 판정했는데도 그
    판정이 사용자에게 전혀 전달 안 됨, fl-2026-08-19-003). 후보 필터링/랭킹
    로직 자체는 안 건드리고(그러면 no_candidates가 되는 범위가 넓어져
    더 큰 변경이 됨), 이미 선택된 상품에 대해 고지만 추가한다."""
    if not keywords:
        return None
    name = str(product.get("product_name") or "").lower()
    brand = str(product.get("brand") or "").lower()
    haystack = name + " " + brand
    missing = [kw for kw in keywords if kw and kw.lower() not in haystack]
    # 전부 일치(정상)하거나 전부 불일치(no_candidates에서 이미 걸러졌어야 할
    # 경우 - 방어적으로 여기서 추측성 문구를 만들지 않고 상위 로직을 신뢰)면 스킵.
    if not missing or len(missing) == len(keywords):
        return None
    return f"주의: 요청하신 '{', '.join(missing)}'는 찾지 못해서 다른 상품을 보여드리는 것입니다."


def _format_preference(preference_context: dict, keywords: list[str], product: dict | None = None) -> str:
    lines = []
    safety_note = _format_safety_substitution(preference_context, keywords)
    if safety_note:
        lines.append(safety_note)
    brand_note = _format_brand_mismatch_note(product, keywords) if product else None
    if brand_note:
        lines.append(brand_note)
    if preference_context and preference_context.get("summary"):
        lines.append(preference_context["summary"])
        keyword_summary = preference_context.get("keyword_summary") or ""
        if keyword_summary:
            lines.append(f"키워드 관련 선호: {keyword_summary}")
    if not lines:
        return "선호 정보 없음 (구매이력 부족)"
    return "\n".join(lines)


_AXIS_REASON = {
    "price": "가격이 저렴해서 골랐어요",
    "review": "리뷰가 좋아서 골랐어요",
    "preference": "평소 선호에 잘 맞아서 골랐어요",
}
_CONDITION_REASON = {
    "최저가": "가격이 가장 저렴해서 골랐어요",
    "가성비": "가성비가 좋아서 골랐어요",
    "빠른배송": "배송이 빨라서 골랐어요",
    "인기순": "인기 있는 상품이라 골랐어요",
    "무료배송": "무료배송이라 골랐어요",
    "리뷰좋은": "리뷰가 좋아서 골랐어요",
}


def _fallback_reason(product: dict, condition: str | None) -> str:
    """RESPONSE_EXPLAIN_PROMPT가 정상 경로에서 쓰는 것과 같은 판단 순서를
    코드로 재현한다(축 기여도 → condition → 기본값) — 새 LLM 호출 없이
    aggregator.py가 이미 계산해둔 axis_contributions만 재사용."""
    contributions = product.get("axis_contributions")
    if contributions:
        top_axis = max(contributions, key=contributions.get)
        if contributions[top_axis] > 0:
            return _AXIS_REASON.get(top_axis, "잘 맞는 상품이라 골랐어요")
    if condition and condition in _CONDITION_REASON:
        return _CONDITION_REASON[condition]
    return "인기 있는 상품이라 골랐어요"


def _fallback_explanation(product: dict, condition: str | None = None) -> str:
    """LLM 실패 또는 빈 설명 시 상품 필드로 최소 문장 생성.

    예전엔 상품명/가격/플랫폼만 나열하고 추천 이유가 아예 빠져 있었다 —
    "핵심 이유가 항상 있어야 한다"는 요구사항을 이 degraded 경로가 못
    지키고 있었다(실측 확인, 사용자 지적). _reflect_elderly는 문장 수/길이/
    어려운 단어만 검사해서 이유 누락을 못 잡는다 — 그래서 여기서 직접
    채운다."""
    name = product.get("name") or "상품"
    price = product.get("price")
    price_str = f"{price:,}원" if isinstance(price, (int, float)) else (str(price) if price else "")
    parts = [name]
    if price_str:
        parts.append(f"{price_str}이에요.")
    parts.append(f"{_fallback_reason(product, condition)}.")
    return " ".join(parts)


def _extract_user_question(state: ShoppingState) -> str | None:
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return msg.get("content")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role == "human":
                return getattr(msg, "content", None)
    return None


# ── 순수 텍스트 생성 — 상태 전이(pending_action/stage)를 모른다 ──────────

_QA_FALLBACK_ANSWER = "죄송해요, 지금은 답변드리기 어려워요. 잠시 후 다시 물어봐 주세요."


def _generate_qa_answer(product: dict, question: str) -> tuple[str, bool, str, bool, bool]:
    """상품 정보를 근거로 사용자 질문에 답변. (answer, reflection_passed, reason, haiku_fallback, degraded)."""
    try:
        answer = retry_call(
            _get_llm().invoke, [HumanMessage(content=RESPONSE_QA_PROMPT.format(
                product_json=json.dumps(product, ensure_ascii=False),
                question=question,
            ))]
        ).content.strip()
    except Exception as e:
        agent_logger.log(f"[response_agent] QA 답변 생성 오류({classify_failure(e).value}): {e} → fallback")
        answer = ""

    if not answer:
        agent_logger.log_graceful_degradation(node="response_agent", reason="qa_llm_failed", stage="response_llm")
        return _QA_FALLBACK_ANSWER, True, "", False, True

    ok, reason = _reflect_elderly(answer)
    haiku_fallback = False
    if not ok:
        agent_logger.log(f"[response_agent] Reflection 실패: {reason} → Haiku 재생성")
        agent_logger.log_quality_regeneration(node="response_agent", reason=reason)
        answer = _simplify_with_haiku(answer, reason)
        haiku_fallback = True
    return answer, ok, reason, haiku_fallback, False


def _generate_explanation(
    product: dict,
    keywords: list[str],
    condition: str | None,
    preference_context: dict,
) -> tuple[str, bool, str, bool, bool]:
    """상품 설명 생성. (explanation, reflection_passed, reason, haiku_fallback, degraded)."""
    try:
        explanation = retry_call(
            _get_llm().invoke, [HumanMessage(content=RESPONSE_EXPLAIN_PROMPT.format(
                product_json=json.dumps(product, ensure_ascii=False),
                keywords=json.dumps(keywords, ensure_ascii=False),
                condition=condition or "없음",
                preference_context=_format_preference(preference_context, keywords, product),
            ))]
        ).content.strip()
    except Exception as e:
        agent_logger.log(f"[response_agent] 설명 생성 오류({classify_failure(e).value}): {e} → fallback")
        explanation = ""

    degraded = False
    if not explanation:
        explanation = _fallback_explanation(product, condition)
        degraded = True
        agent_logger.log(f"[response_agent] fallback 설명: {explanation}")
        agent_logger.log_graceful_degradation(node="response_agent", reason="explain_llm_failed", stage="response_llm")

    ok, reason = _reflect_elderly(explanation)
    haiku_fallback = False
    if not ok:
        agent_logger.log(f"[response_agent] Reflection 실패: {reason} → Haiku 재생성")
        agent_logger.log_quality_regeneration(node="response_agent", reason=reason)
        explanation = _simplify_with_haiku(explanation, reason)
        haiku_fallback = True

    return explanation, ok, reason, haiku_fallback, degraded


# ── 상태 전이 — "구매 확인으로 넘어갈지"는 여기만 안다 ────────────────────

def _build_confirm_pending_action(explanation: str, quantity) -> dict:
    """설명 + 구매 확인 문구를 product_confirm pending_action으로 조합."""
    explanation_clean = explanation
    for cta in _CTA_ENDINGS:
        if explanation_clean.endswith(cta):
            explanation_clean = explanation_clean[: -len(cta)].rstrip(" .·\n")
            break

    pending_msg = "주문할까요?" if quantity else "주문을 원하시면 수량을 말씀해 주세요."
    return {"type": "product_confirm", "message": f"{explanation_clean}\n{pending_msg}"}


# ── 배송지 조회 — 상품 설명과 무관한 별도 책임, QA 분기 안에서 지름길로만 탐 ──

def _is_address_question(question: str) -> bool:
    return any(k in question for k in _ADDRESS_KEYWORDS)


def _answer_address_question(state: ShoppingState) -> dict:
    """배송지 조회 질문 — 상품 없어도 바로 답변."""
    from src.tools.mock_tools import mock_get_default_address
    user_id = state.get("user_id", "")
    addr = mock_get_default_address(user_id)
    if addr:
        addr_text = " ".join(filter(None, [
            addr.get("address_line1"), addr.get("address_line2")
        ]))
        msg = f"등록된 배송지는 {addr_text}이에요."
    else:
        msg = "등록된 배송지가 없어요. 배송지를 알려주시면 저장해 드릴게요."
    return {
        "explanation": msg,
        "pending_action": {"type": "address_confirm", "message": msg},
        "stage": state.get("stage", "idle"),
        "last_agent": "response_agent",
        "error": None,
    }


def response_agent_node(state: ResponseAgentInput) -> ResponseAgentUpdate:
    intent = state.get("intent")
    keywords = state.get("keywords") or []
    condition = state.get("condition")
    recommendation_context = state.get("recommendation_context") or {}
    preference_context = recommendation_context.get("preference_context") or {}
    recommended_products = state.get("recommended_products") or []
    current_idx = state.get("current_product_index") or 0

    # ── 상품 결정 전 조언(WON-23 Unit 3) ── 카탈로그 검색 없이 텍스트만
    # 응답한다는 설계를 지키기 위해 recommended_products/product_agent를
    # 전혀 참조하지 않는다 — user_input만 LLM에 넘긴다.
    if intent == "product_decision_advice":
        user_input = _extract_user_question(state) or ""
        answer, ok, reason, replaced, degraded = _generate_advice_answer(user_input)
        agent_logger.log(f"[response_agent] 조언 답변: {answer}")
        return {
            "explanation": answer,
            "reflection_passed": ok,
            "reflection_reason": reason,
            "haiku_fallback": replaced,
            "pending_action": {"type": "clarification", "message": answer, "payload": {}},
            "needs_clarification": False,
            "stage": "idle",
            "last_agent": "response_agent",
            "error": None,
            "degraded_mode": degraded,
            "failure_stage": "response_llm" if degraded else None,
        }

    # ── QA ──
    if intent == "ask":
        target = state.get("selected_product") or (
            recommended_products[current_idx] if recommended_products else None
        )
        user_question = _extract_user_question(state)

        if user_question and _is_address_question(user_question):
            return _answer_address_question(state)

        if not target or not user_question:
            return {
                "stage": state.get("stage", "idle"),
                "needs_clarification": True,
                "pending_action": {
                    "type": "clarification",
                    "message": "어떤 상품에 대해 물어보시는 건지 먼저 알려주세요.",
                    "payload": {},
                },
                "last_agent": "response_agent",
                "error": None,
            }

        answer, ok, reason, haiku_fallback, degraded = _generate_qa_answer(target, user_question)
        agent_logger.log(f"[response_agent] QA 답변: {answer}")
        # respond_node의 분기 우선순위(pending_action.message가 explanation보다
        # 먼저 확인됨, nodes.py 참고)상 pending_action을 안 건드리면 이 답변이
        # 화면에 아예 안 뜨고 예전 확인 문구만 반복된다(WON-19 Unit 4 확장 —
        # 결제 질문만이 아니라 product_confirm 중 모든 상품 질문에서 실측 확인).
        # _answer_address_question과 동일하게, 답변을 원래 확인 문구 앞에
        # 붙여서 pending_action을 직접 갱신한다 — 원래 대기 상태(type)는 그대로
        # 유지해 "질문에 답하고 다시 확인 대기로 복귀"를 보장한다.
        original_pending = state.get("pending_action") or {}
        original_message = original_pending.get("message", "")
        combined_message = f"{answer}\n{original_message}" if original_message else answer
        return {
            "explanation": answer,
            "reflection_passed": ok,
            "haiku_fallback": haiku_fallback,
            "reflection_reason": reason,
            "pending_action": {
                "type": original_pending.get("type") or "product_confirm",
                "message": combined_message,
            },
            "stage": "product_confirming",
            "last_agent": "response_agent",
            "error": None,
            "degraded_mode": degraded,
            "failure_stage": "response_llm" if degraded else None,
        }

    # ── 설명 생성 ──
    product = state.get("selected_product")
    if not product:
        return {"stage": "idle", "error": "no_product", "last_agent": "response_agent"}

    explanation, ok, reason, haiku_fallback, degraded = _generate_explanation(
        product, keywords, condition, preference_context,
    )
    agent_logger.log(f"[response_agent] 설명: {explanation}")

    return {
        "explanation": explanation,
        "reflection_passed": ok,
        "haiku_fallback": haiku_fallback,
        "reflection_reason": reason,
        "pending_action": _build_confirm_pending_action(explanation, state.get("quantity")),
        "stage": "product_confirming",
        "last_agent": "response_agent",
        "error": None,
        "degraded_mode": degraded,
        "failure_stage": "response_llm" if degraded else None,
    }
