"""
Fallback Orchestrator Node.

역할: 결정론적 workflow(router.py::route())가 막혔을 때만(Stuck Trigger,
fallback_stuck_turns>=1) 호출된다 — intent_agent를 대체하지 않고, intent_agent가
구조적으로 못 보는 여러 턴 맥락(recommendation_context, 최근 대화)까지 보고
"왜 막혔는지" 진단해서 3가지 복구 전략(recover/clarify/chat) 중 하나를 고른다.

recover는 state를 patch하고 route()를 그대로 재호출해 정상 흐름으로 복귀시킨다
(신규 라우팅 로직 없음). clarify/chat은 pending_action.type="clarification"으로
통일해서 respond로 보낸다 — respond_node의 분기 순서(needs_clarification을 먼저
False로 내려두면 pending_action.message 분기가 stage와 무관하게 항상 이 메시지를
쓴다)에 안전하게 올라타기 위함.

설계 문서: C:\\Users\\82108\\.claude\\plans\\radiant-questing-map.md
"""
from typing import Any, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from configs.llm_config import get_llm
from src.state.node_inputs import FallbackOrchestratorInput, FallbackOrchestratorUpdate
from src.prompts.fallback_prompt import (
    FALLBACK_ORCHESTRATOR_PROMPT,
    SYSTEM_MAP_TEXT,
    RECOVERY_POLICY_TEXT,
    _STAGE_HINT,
)
from src.utils.agent_logger import agent_logger
from src.utils.retry import retry_call
from src.agents.satisfaction_checkin import (
    pick_satisfaction_candidate,
    start_satisfaction_checkin,
    capture_satisfaction_answer,
)

# route()가 이 값들을 안전하게 다시 판단할 수 있는 intent만 허용한다 — "confirm"/
# "deny"/"quantity_change"/"address_change"/"cancel" 등은 stage에 따라 payment_agent/
# cancel로 곧장 갈 수 있어서(_route_product_confirming 등), fallback이 실수로
# 세팅하면 결제/취소가 잘못 트리거될 위험이 있다. recover는 어디까지나 "검색/조회
# 방향"으로만 복구한다.
_SAFE_INTENTS = frozenset({"buy", "reorder", "refine", "compare_platforms", "ask", "next"})

_STATE_PATCH_FIELDS = ("intent", "keywords", "quantity", "condition", "exclude_keywords")

_DEFAULT_CLARIFY_FALLBACK = "죄송해요, 잘 이해하지 못했어요. 어떤 상품을 찾으시는지 조금 더 자세히 말씀해 주시겠어요?"


class FallbackDecision(BaseModel):
    action: str = Field(
        description='"recover"(기존 정보로 확실히 복구 가능) | "clarify"(정보 부족/모호함) | '
        '"chat"(쇼핑과 무관한 순수 응대) 중 하나.'
    )
    corrected_intent: Optional[str] = Field(
        default=None,
        description="action=recover일 때만. buy/reorder/refine/compare_platforms/ask/next 중 하나만.",
    )
    corrected_keywords: Optional[list[str]] = Field(default=None, description="action=recover일 때만. 확정된 상품명/카테고리.")
    corrected_quantity: Optional[int] = Field(default=None, description="action=recover일 때만.")
    corrected_condition: Optional[str] = Field(default=None, description="action=recover일 때만.")
    corrected_exclude_keywords: Optional[list[str]] = Field(default=None, description="action=recover일 때만.")
    reset_product_context: bool = Field(
        default=False, description="사용자 목적 자체가 이전과 다르게 바뀐 경우에만 true."
    )
    clarify_message: Optional[str] = Field(default=None, description="action=clarify일 때 되물을 짧고 구체적인 질문.")
    chat_reply: Optional[str] = Field(default=None, description="action=chat일 때 쇼핑과 무관한 짧고 따뜻한 한 문장.")
    reasoning: str = Field(default="", description="판단 근거(로그용, 사용자에게 안 보임).")


_fallback_llm = None
_structured_fallback_llm = None


def _get_llm():
    global _fallback_llm, _structured_fallback_llm
    if _fallback_llm is None:
        _fallback_llm = get_llm("fallback", temperature=0.2, retry_owner="application")
        _structured_fallback_llm = _fallback_llm.with_structured_output(FallbackDecision)
    return _structured_fallback_llm


def _format_recent_messages(messages: Optional[list], n: int = 6) -> str:
    recent = (messages or [])[-n:]
    lines: list[str] = []
    for msg in recent:
        if isinstance(msg, dict):
            role = msg.get("role") or msg.get("type") or "?"
            content = msg.get("content", "")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None) or "?"
            content = getattr(msg, "content", "")
        speaker = "사용자" if role in ("user", "human") else "시스템"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines) if lines else "없음"


def _summarize_recommendation_context(rc: Optional[dict[str, Any]]) -> str:
    if not rc:
        return "없음"
    pref = rc.get("preference_context") or {}
    parts: list[str] = []
    if purchase_count := rc.get("purchase_count"):
        parts.append(f"구매이력 {purchase_count}건")
    if summary := pref.get("summary"):
        parts.append(summary)
    keyword_history = pref.get("keyword_history") or []
    names = ", ".join(h["product_name"] for h in keyword_history[:5] if h.get("product_name"))
    if names:
        parts.append(f"최근 관련 구매: {names}")
    soft_preferences = pref.get("soft_preferences") or []
    values = ", ".join(s["value"] for s in soft_preferences[:5] if s.get("value"))
    if values:
        parts.append(f"선호 신호: {values}")
    return " / ".join(parts) if parts else "없음"


def _render_pending_action(pa: Optional[dict[str, Any]]) -> str:
    if not pa:
        return "없음"
    return f"type={pa.get('type')}, message={pa.get('message')!r}"


def _build_trigger_reason(state: FallbackOrchestratorInput) -> str:
    """트리거 감지는 항상 router.py(코드)의 몫이고, 여기선 이미 감지된 이유를
    문자열로 재구성해서 보여주기만 한다 — LLM이 "왜 불려왔는지"를 추측하지
    않게 하기 위함. 지금은 Stuck Trigger 한 종류뿐이지만, 나중에 다른 트리거가
    추가돼도 이 함수만 그 트리거의 이유를 반영하도록 확장하면 된다."""
    reasons = []
    if state.get("needs_clarification"):
        reasons.append("needs_clarification=True")
    confidence = state.get("confidence")
    if confidence is not None and confidence < 0.5:
        reasons.append(f"confidence={confidence}")
    if state.get("intent") == "unclear":
        reasons.append("intent=unclear")
    stuck_turns = state.get("fallback_stuck_turns") or 0
    base = ", ".join(reasons) or "알 수 없음"
    return f"정해진 재질문으로도 해결되지 않고 연속 {stuck_turns}번째 막힘 ({base})"


def _build_prompt(state: FallbackOrchestratorInput) -> str:
    stage = state.get("stage", "idle")
    return FALLBACK_ORCHESTRATOR_PROMPT.format(
        system_map=SYSTEM_MAP_TEXT,
        recovery_policy=RECOVERY_POLICY_TEXT,
        stage_hint=_STAGE_HINT.get(stage, "특별히 조심할 점 없음."),
        trigger_reason=_build_trigger_reason(state),
        stage=stage,
        pending_action=_render_pending_action(state.get("pending_action")),
        intent=state.get("intent") or "없음",
        confidence=state.get("confidence"),
        needs_clarification=state.get("needs_clarification"),
        clarification_reason=state.get("clarification_reason") or "없음",
        keywords=state.get("keywords") or [],
        quantity=state.get("quantity"),
        condition=state.get("condition"),
        exclude_keywords=state.get("exclude_keywords") or [],
        recommendation_summary=_summarize_recommendation_context(state.get("recommendation_context")),
        recent_messages=_format_recent_messages(state.get("messages")),
    )


def _clarify_result(message: str, payload: Optional[dict[str, Any]] = None) -> FallbackOrchestratorUpdate:
    pending_action: dict[str, Any] = {"type": "clarification", "message": message}
    if payload:
        pending_action["payload"] = payload
    return {
        "pending_action": pending_action,
        "needs_clarification": False,
        "clarification_reason": None,
        "last_agent": "fallback_orchestrator",
    }


def _extract_last_user_text(messages: Optional[list]) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, dict):
            content = msg.get("content")
            role = msg.get("role") or msg.get("type")
            if content and role in (None, "user", "human"):
                return str(content)
        else:
            content = getattr(msg, "content", None)
            msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
            if content and msg_type in (None, "human", "user"):
                return str(content)
    return ""


def _recover_result(decision: FallbackDecision) -> FallbackOrchestratorUpdate:
    updates: FallbackOrchestratorUpdate = {}

    if decision.reset_product_context:
        # cancel_node(src/agents/nodes.py)가 리셋하는 필드 목록과 동일한 발상 —
        # 사용자 목적 자체가 바뀌었으면 이전 상품/검색 흔적이 새 목적과 섞이면 안 된다.
        updates.update({
            "search_results": [],
            "selected_product": None,
            "product_url": None,
            "explanation": None,
            "highlight_specs": [],
            "current_product_index": 0,
            "pending_action": None,
            "quantity": None,
        })

    if decision.corrected_intent in _SAFE_INTENTS:
        updates["intent"] = decision.corrected_intent
    elif decision.corrected_intent:
        agent_logger.log(f"[fallback_orchestrator] 안전하지 않은 corrected_intent 무시: {decision.corrected_intent!r}")

    if decision.corrected_keywords is not None:
        updates["keywords"] = decision.corrected_keywords
    if decision.corrected_quantity is not None:
        updates["quantity"] = decision.corrected_quantity
    if decision.corrected_condition is not None:
        updates["condition"] = decision.corrected_condition
    if decision.corrected_exclude_keywords is not None:
        updates["exclude_keywords"] = decision.corrected_exclude_keywords

    updates["needs_clarification"] = False
    updates["clarification_reason"] = None
    updates["fallback_stuck_turns"] = 0
    updates["last_agent"] = "fallback_orchestrator"
    # route()의 조기 종료 게이트는 needs_clarification 외에도 confidence<0.5나
    # intent=="unclear"만으로도 발동한다 — 이번 턴 intent_agent가 이미 남겨둔
    # 낮은 confidence를 안 고치면, recover로 정상 슬롯을 채워도 route()가
    # 다시 같은 게이트에 걸려 respond로 새버린다. recover는 "이제 확실히
    # 안다"는 판단이므로 confidence를 명시적으로 올려둔다.
    updates["confidence"] = 0.9
    return updates


def fallback_orchestrator_node(state: FallbackOrchestratorInput) -> FallbackOrchestratorUpdate:
    agent_logger.log(
        f"\n{'─'*40}\n[fallback_orchestrator] 진입 | stage={state.get('stage')} "
        f"intent={state.get('intent')} stuck_turns={state.get('fallback_stuck_turns')}\n{'─'*40}"
    )

    # 직전 턴에 만족도 체크인을 걸어놨었다면(router.py::route()가
    # pending_action.payload.satisfaction_check만 보고 여기로 결정적으로
    # 보냄 — LLM 진단 없이), 이번 턴은 그 답변을 해석하는 턴이다. 새로
    # recover/clarify/chat을 판단할 필요가 없다.
    pending_check = ((state.get("pending_action") or {}).get("payload") or {}).get("satisfaction_check")
    if pending_check:
        user_text = _extract_last_user_text(state.get("messages"))
        reply = capture_satisfaction_answer(state.get("user_id", ""), pending_check, user_text)
        result = _clarify_result(reply)
        result["fallback_stuck_turns"] = 0  # 체크인 마무리 - 다시 정상 대기 상태로
        return result

    prompt = _build_prompt(state)
    try:
        llm = _get_llm()
        decision = retry_call(llm.invoke, [HumanMessage(content=prompt)])
        if not isinstance(decision, FallbackDecision):
            raise ValueError("structured output 파싱 실패")
    except Exception as e:
        agent_logger.log(f"[fallback_orchestrator] LLM 호출 실패, 안전한 clarify로 대체: {e}")
        return _clarify_result(_DEFAULT_CLARIFY_FALLBACK)

    agent_logger.log(f"[fallback_orchestrator] action={decision.action} reasoning={decision.reasoning}")

    if decision.action == "recover":
        # recover인데 intent를 안 고쳤고(corrected_intent 없음) 이번 턴 intent가
        # 여전히 unclear면, route()의 게이트가 intent=="unclear" 조건으로 다시
        # respond가 아니라 fallback_orchestrator를 무한 반복 호출할 위험이 있다
        # (confidence는 여기서 올리지만 intent=="unclear" 자체가 게이트 조건이라
        # 그것만으로는 안 풀림). 이런 불완전한 recover는 신뢰하지 않고 clarify로
        # 안전하게 처리한다.
        if not decision.corrected_intent and state.get("intent") in (None, "unclear"):
            agent_logger.log("[fallback_orchestrator] recover인데 intent 교정이 없어 clarify로 강등")
            return _clarify_result(decision.clarify_message or _DEFAULT_CLARIFY_FALLBACK)
        return _recover_result(decision)
    if decision.action == "chat":
        # 잡담으로 끝내기보다, 아직 만족도를 안 물어본 구매이력이 있으면 그걸
        # 되물어서 죽어있던 satisfaction_score/memo 필드에 처음으로 실제
        # 용도를 준다(사용자 요청). 후보가 없거나 질문 생성이 실패하면 기존
        # 그대로 일반 chat 응답으로 대체한다.
        user_id = state.get("user_id")
        candidate = pick_satisfaction_candidate(user_id) if user_id else None
        if candidate:
            pending_action = start_satisfaction_checkin(candidate)
            if pending_action:
                return {
                    "pending_action": pending_action,
                    "needs_clarification": False,
                    "clarification_reason": None,
                    "last_agent": "fallback_orchestrator",
                }
        return _clarify_result(decision.chat_reply or _DEFAULT_CLARIFY_FALLBACK)
    # action == "clarify" 또는 예상 밖의 값 — 안전하게 clarify로 처리
    return _clarify_result(decision.clarify_message or _DEFAULT_CLARIFY_FALLBACK)
