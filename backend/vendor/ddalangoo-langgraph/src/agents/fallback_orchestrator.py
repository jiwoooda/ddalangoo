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
from src.state.schema import product_context_reset, purchase_flow_reset
from src.prompts.fallback_prompt import (
    FALLBACK_ORCHESTRATOR_PROMPT,
    SYSTEM_MAP_TEXT,
    RECOVERY_POLICY_TEXT,
    _STAGE_HINT,
)
from src.utils.agent_logger import agent_logger
from src.utils.retry import retry_call
from src.agents.satisfaction_checkin import capture_satisfaction_answer
from src.agents.profile_topup import capture_profile_topup_answer
from src.agents.casual_engagement import pick_and_start_engagement

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
    if state.get("error") == "reorder_exhausted":
        # reorder_agent가 구매이력 후보를 다 보여줬는데도(remaining_candidates
        # 소진) 사용자가 원하는 걸 못 찾은 경우 — 재구매가 아니라 처음 사는
        # 상품일 가능성이 있다는 힌트를 LLM에게 명시적으로 준다(fl-2026-08-26-002).
        reasons.append("reorder_exhausted(재구매 후보를 다 보여줬는데도 못 찾음)")
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


def _should_reset_product_context(
    state: FallbackOrchestratorInput, decision: FallbackDecision
) -> bool:
    """'사용자 목적이 바뀌었는가' — 이전 상품 탐색/구매 플로우 문맥을 초기화할지의
    단일 판단 지점(WON-20 Unit 3).

    - state["goal_shift"]가 True 면(Unit 2 intent_agent가 이 발화를 이미
      high-confidence out_of_scope 로 판정) 재확인 없이 신뢰해 리셋한다 — "분류와
      행동 분리": '무엇이 바뀌었나'는 Unit 2가, '무엇을 할까'(action)는 이 노드가.
    - goal_shift 가 False/None 이면(Unit 2가 out_of_scope 로는 안 본 애매한 영역)
      기존처럼 LLM 의 자유 판단(decision.reset_product_context)을 그대로 쓴다.

    배선 버그 수정: 이 판단은 이제 action(recover/clarify/chat)과 무관하게
    적용된다 — 예전엔 _recover_result() 안에서만 읽혀 action=chat/clarify 면
    LLM 이 옳게 reset=true 를 내도 버려졌다(WON-39 실측)."""
    if state.get("goal_shift"):
        return True
    return bool(decision.reset_product_context)


def _with_context_reset(
    update: FallbackOrchestratorUpdate, do_reset: bool
) -> FallbackOrchestratorUpdate:
    """do_reset 이면 WON-37 카테고리 함수로 이전 상품 탐색/구매 플로우 문맥을
    초기화한 뒤 그 위에 원래 update 를 얹는다 — pending_action/needs_clarification
    등 action 별 결정값이 항상 우선한다. 새 리셋 로직은 만들지 않고
    product_context_reset()+purchase_flow_reset() 을 그대로 재사용한다. 단
    **장바구니(cart_items)는 유지한다** — 목적이 바뀌었어도 담아둔 건 그대로다
    (WON-37 결정, cart_clear() 안 씀).

    action=chat/clarify 갈래에 쓴다 — 배선 버그 수정의 핵심(예전엔 이 갈래에서
    리셋이 아예 안 됐다). recover 갈래는 _recover_result(decision, do_reset) 가
    같은 두 헬퍼로 자체 처리한다(WON-37 배선 테스트가 그 소스를 검사)."""
    if not do_reset:
        return update
    merged: FallbackOrchestratorUpdate = {}
    merged.update(product_context_reset())
    merged.update(purchase_flow_reset())
    merged.update(update)
    return merged


def _recover_result(
    decision: FallbackDecision, do_reset: Optional[bool] = None
) -> FallbackOrchestratorUpdate:
    updates: FallbackOrchestratorUpdate = {}

    # do_reset 은 호출부(fallback_orchestrator_node)가 _should_reset_product_context()
    # 로 판단한 값 — goal_shift(Unit 2) 우선, 없으면 LLM 판단(WON-20 Unit 3). 그래프
    # 밖에서 decision 만으로 직접 호출하는 경우(테스트 등)엔 None 이 들어오므로 예전처럼
    # decision.reset_product_context 로 폴백한다.
    reset = decision.reset_product_context if do_reset is None else do_reset
    if reset:
        # WON-37 — 사용자 목적 자체가 바뀌었으면 이전 상품 탐색/구매 플로우 문맥은
        # 새 목적과 섞이면 안 된다. schema 카테고리 함수 조합으로 초기화한다
        # (cancel_node / 결제완료와 같은 헬퍼). 단 **장바구니(cart_items)는
        # 유지한다** — 목적이 바뀌었어도 담아둔 건 그대로다(cart_clear() 안 씀).
        # 아래 corrected_* 교정값이 이 기본값 위에 덮어쓴다(intent/keywords/quantity/
        # condition/exclude_keywords).
        updates.update(product_context_reset())
        updates.update(purchase_flow_reset())

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


def _looks_like_new_request(state: FallbackOrchestratorInput) -> bool:
    """만족도/프로필 되물음에 대한 답변 턴인데, intent_agent가 이번 턴 발화를
    이미 명확한 새 쇼핑 요청으로 분류해뒀다면(예: "아니 됐고 우유나 사줘") —
    사이드 대화 해석을 강행하지 않는다. intent_agent는 이 노드보다 먼저 항상
    실행되므로 이번 턴 분류 결과가 이미 state에 있다 — 별도 LLM 호출 없이
    이미 계산된 값만 재사용한다."""
    return (
        state.get("intent") in _SAFE_INTENTS
        and not state.get("needs_clarification")
        and (state.get("confidence") or 0.0) >= 0.5
    )


def fallback_orchestrator_node(state: FallbackOrchestratorInput) -> FallbackOrchestratorUpdate:
    agent_logger.log(
        f"\n{'─'*40}\n[fallback_orchestrator] 진입 | stage={state.get('stage')} "
        f"intent={state.get('intent')} stuck_turns={state.get('fallback_stuck_turns')}\n{'─'*40}"
    )

    # 직전 턴에 만족도 체크인/프로필 이어 묻기를 걸어놨었다면(router.py::route()가
    # pending_action.payload만 보고 여기로 결정적으로 보냄 — LLM 진단 없이),
    # 이번 턴은 그 답변을 해석하는 턴이다. 새로 recover/clarify/chat을 판단할
    # 필요가 없다.
    payload = (state.get("pending_action") or {}).get("payload") or {}
    pending_check = payload.get("satisfaction_check")
    pending_topup = payload.get("profile_topup")
    if pending_check or pending_topup:
        if _looks_like_new_request(state):
            # 사용자가 사이드 질문에 답하는 대신 목적 있는 새 요청으로 들어왔다
            # — 만족도/프로필 해석을 포기하고 pending_action만 비운다. after_
            # fallback_orchestrator가 pending_action이 clarification이 아님을
            # 보고 route()를 그대로 재호출 — 이번 턴 intent_agent가 이미 정확히
            # 분류해둔 값(예: intent=buy, keywords=["우유"])으로 바로 정상
            # 쇼핑 흐름(context_agent 등)에 진입한다. 신규 라우팅 로직 없음.
            agent_logger.log(
                f"[fallback_orchestrator] 사이드 대화 도중 새 요청 감지(intent={state.get('intent')}) "
                "- 만족도/프로필 해석 포기하고 정상 흐름으로 복귀"
            )
            return {"pending_action": None, "last_agent": "fallback_orchestrator"}
        if pending_check:
            user_text = _extract_last_user_text(state.get("messages"))
            reply = capture_satisfaction_answer(state.get("user_id", ""), pending_check, user_text)
            result = _clarify_result(reply)
            result["fallback_stuck_turns"] = 0  # 체크인 마무리 - 다시 정상 대기 상태로
            return result
        user_text = _extract_last_user_text(state.get("messages"))
        reply = capture_profile_topup_answer(state.get("user_id", ""), pending_topup, user_text)
        result = _clarify_result(reply)
        result["fallback_stuck_turns"] = 0
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

    # WON-20 Unit 3 — 목적 전환 시 문맥 초기화 여부는 action 종류와 무관하게 한
    # 곳에서 판단하고, 아래 세 갈래(recover/chat/clarify) 모두에 동일하게 적용한다.
    do_reset = _should_reset_product_context(state, decision)

    if decision.action == "recover":
        if (
            state.get("active_failure") is not None
            and decision.corrected_intent not in _SAFE_INTENTS
        ):
            agent_logger.log(
                "[fallback_orchestrator] active_failure recover에 안전한 intent 보정이 없어 clarify로 강등"
            )
            return _with_context_reset(
                _clarify_result(decision.clarify_message or _DEFAULT_CLARIFY_FALLBACK), do_reset
            )
        # recover인데 intent를 안 고쳤고(corrected_intent 없음) 이번 턴 intent가
        # 여전히 unclear면, route()의 게이트가 intent=="unclear" 조건으로 다시
        # respond가 아니라 fallback_orchestrator를 무한 반복 호출할 위험이 있다
        # (confidence는 여기서 올리지만 intent=="unclear" 자체가 게이트 조건이라
        # 그것만으로는 안 풀림). 이런 불완전한 recover는 신뢰하지 않고 clarify로
        # 안전하게 처리한다.
        if not decision.corrected_intent and state.get("intent") in (None, "unclear"):
            agent_logger.log("[fallback_orchestrator] recover인데 intent 교정이 없어 clarify로 강등")
            return _with_context_reset(
                _clarify_result(decision.clarify_message or _DEFAULT_CLARIFY_FALLBACK), do_reset
            )
        return _recover_result(decision, do_reset)
    if decision.action == "chat":
        # 잡담으로 끝내기보다 목적 있는 대화로 채운다 — casual_engagement.py의
        # 공용 우선순위(만족도 체크인 → 프로필 이어 묻기)를 그대로 재사용한다.
        # entry_engagement_node(세션 시작 트리거)와 같은 로직을 공유 — 여기
        # 인라인으로 두 벌 유지하지 않는다. 둘 다 없으면 기존처럼 일반 chat 응답.
        pending_action = pick_and_start_engagement(state.get("user_id", ""))
        if pending_action:
            return _with_context_reset({
                "pending_action": pending_action,
                "needs_clarification": False,
                "clarification_reason": None,
                "last_agent": "fallback_orchestrator",
            }, do_reset)
        return _with_context_reset(
            _clarify_result(decision.chat_reply or _DEFAULT_CLARIFY_FALLBACK), do_reset
        )
    # action == "clarify" 또는 예상 밖의 값 — 안전하게 clarify로 처리
    return _with_context_reset(
        _clarify_result(decision.clarify_message or _DEFAULT_CLARIFY_FALLBACK), do_reset
    )
