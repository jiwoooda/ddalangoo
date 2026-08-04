"""
Smalltalk Agent Node.

역할: 신규유저(구매이력 0건, 미온보딩) 진입 시 코드 레벨 게이트
(src/graph/router.py의 route_entry)가 intent_agent를 거치지 않고 바로 이
노드로 라우팅한다 — smalltalk는 LLM이 매 턴 판단하는 intent가 아니라, 신규유저
진입 시 자동으로 시작되는 온보딩 이벤트다.

온보딩은 한 턴짜리 인사로 끝날 수도, 여러 턴에 걸친 대화로 이어질 수도 있다.
매 턴 LLM이 스스로 onboarding_complete를 판단한다 — 이번 대화에서 스키마가
얼마나 채워졌는지(collected_so_far, src.state.smalltalk_schema.format_smalltalk_profile)를
프롬프트에 보여줘서, 충분히 파악됐다 싶으면 자연스럽게 마무리하도록 유도한다.
false인 동안은 다음 턴도 route_entry가 계속 이 노드로 보내고, true가 되면
profile.onboarded_at을 찍어 그 다음 턴부터 intent_agent가 정상적으로 관여한다.

대화가 너무 길어지는 걸 막는 안전장치로 온보딩 시작 시각
(state.onboarding_started_at, 1턴째에 기록)부터 _MAX_ONBOARDING_MINUTES가
지나면, LLM에게 이번 턴엔 자연스럽게 마무리해달라고 프롬프트로 미리
안내한다(wrap_up_instruction) — 그래도 LLM이 onboarding_complete=false를
반환하면 그때 가서야 최후 수단으로 코드가 강제 종료한다(정상 경로가 아니라
예외 상황 대비용). 음성 대화라 턴 수만으론 실제 경과 시간을 가늠할 수 없어
턴 수 대신 시각을 쓴다.

이 노드는 "구조화된 수집기"다 — SmalltalkProfileSchema를 채워 profile에
누적 저장할 뿐, soft_preference/explicit_exclusion 같은 tier 분류는 하지
않는다. tier 분류는 context_agent가 이 profile 데이터를 읽어서 담당한다
(context_agent.build_preference_context 참고).
"""
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.errors import NodeError
from langgraph.runtime import Runtime
from langgraph.types import Command

from configs.llm_config import get_llm
from src.state.schema import ShoppingState
from src.state.node_inputs import SmalltalkAgentInput, SmalltalkAgentUpdate
from src.state.smalltalk_schema import SmalltalkProfileSchema, format_smalltalk_profile
from src.prompts.smalltalk_prompt import (
    SMALLTALK_CHAT_PROMPT,
    SMALLTALK_GREETING_PROMPT,
    SMALLTALK_ORDER_HANDOFF_RULE,
    SMALLTALK_PROFILE_FIELD_GUIDE,
    SMALLTALK_TOPIC_GUIDE,
)
from src.tools import db_client
from src.utils.agent_logger import agent_logger
from src.utils.retry import FailureClass, classify_failure


class SmalltalkOutput(BaseModel):
    reply: str
    preferred_name: Optional[str] = Field(
        default=None,
        description="사용자가 불려지고 싶어하는 이름/호칭 (예: '철수님', '아저씨'). "
        "선호도가 아니라 호칭 정보라 SmalltalkProfileSchema가 아닌 별도 필드로 둔다 — "
        "context_agent의 tier1~3 분류 대상이 아니다.",
    )
    new_allergens: list[str] = Field(default_factory=list, description="알레르기 (안전 기준, 배제용)")
    new_diet_restrictions: list[str] = Field(default_factory=list, description="식이제한 (안전 기준, 배제용)")
    profile: SmalltalkProfileSchema = Field(default_factory=SmalltalkProfileSchema)
    onboarding_complete: bool = Field(
        default=False,
        description="온보딩 대화를 마무리해도 될지. 선호도 정보가 충분히 모였거나, "
        "사용자가 특정 상품 구매 등 쇼핑 의사를 명확히 보이면 true.",
    )


_MAX_ONBOARDING_MINUTES = 30

_WRAP_UP_INSTRUCTION = """\
# 대화가 길어졌습니다
대화가 꽤 오래 이어졌어요. 이번 턴엔 자연스럽게 마무리하는 인사를 하고
onboarding_complete=true로 하세요(예: "오늘 이야기 즐거웠어요, 필요하신 거
있으면 언제든 불러주세요!"). 사용자가 하고 싶은 말이 남아있다면 짧게
들어주되, 대화를 이어가려 하지 말고 마무리하는 톤으로 답하세요.
"""


def _count_user_turns(messages: list) -> int:
    """로그용 — 턴 번호 표시 외에 종료 판단에는 안 쓴다(_MAX_ONBOARDING_MINUTES 참고)."""
    count = 0
    for msg in messages:
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                count += 1
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role == "human":
                count += 1
    return count


def _onboarding_elapsed_minutes(started_at: str | None) -> float:
    if not started_at:
        return 0.0
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return 0.0
    return (datetime.now(timezone.utc) - started).total_seconds() / 60


_llm: BaseChatModel | None = None


def _get_llm() -> BaseChatModel:
    global _llm
    if _llm is None:
        # retry_owner="application": 이 노드는 NODE_RETRY_POLICY로 재시도되므로
        # anthropic/openai SDK 자체 재시도는 꺼서 중첩 재시도를 막는다.
        _llm = get_llm("context", temperature=0.3, max_tokens=300, retry_owner="application")
    return _llm


def _extract_user_input(state: ShoppingState) -> str:
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return msg.get("content", "")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role == "human":
                return getattr(msg, "content", "")
    return ""


def _format_conversation(messages: list) -> str:
    """직전까지의 대화를 사람이 읽을 수 있는 텍스트로. 마지막(현재) 발화는
    호출부에서 이미 제외하고 넘긴다 — {user_input}과 중복 노출 방지."""
    lines = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content", "")
        else:
            raw_role = getattr(msg, "type", None) or getattr(msg, "role", None)
            role = "user" if raw_role == "human" else ("assistant" if raw_role in ("ai", "assistant") else raw_role)
            content = getattr(msg, "content", "")
        if not content:
            continue
        speaker = "사용자" if role == "user" else "딸랑구"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def _merge_profile_signals(user_id: str, result: SmalltalkOutput, mark_onboarded: bool) -> None:
    """
    이번 턴에 온보딩이 끝났다고 판단되면(mark_onboarded=True) 신호가 하나도
    안 잡혀도 profile에 onboarded_at을 남겨야 한다 — 이게 없으면
    route_entry(src/graph/router.py)가 다음 턴에도 계속 이 노드로 보내서
    온보딩이 끝나지 않는다. 온보딩 진행 중인 턴(mark_onboarded=False)은
    뭔가 실제로 추출됐을 때만 저장한다 — 매번 profile을 갱신하면
    save_profile의 computed_at도 매번 갱신돼서 RoutedSignal(general_context)의
    timestamp 의미가 흐려진다.
    """
    profile = db_client.get_profile(user_id) or {}
    merged = dict(profile)
    changed = False

    if result.preferred_name:
        merged["preferred_name"] = result.preferred_name
        changed = True
    if result.new_allergens:
        merged["allergens"] = db_client.merge_list_field(profile.get("allergens"), result.new_allergens)
        changed = True
    if result.new_diet_restrictions:
        merged["diet_restrictions"] = db_client.merge_list_field(
            profile.get("diet_restrictions"), result.new_diet_restrictions
        )
        changed = True

    p = result.profile
    if p.food_dislikes:
        merged["food_dislikes"] = db_client.merge_list_field(profile.get("food_dislikes"), p.food_dislikes)
        changed = True
    if p.value_priority:
        merged["value_priority"] = p.value_priority
        changed = True
    if p.delivery_priority:
        merged["delivery_priority"] = p.delivery_priority
        changed = True
    if p.household_size is not None:
        merged["household_size"] = p.household_size
        changed = True
    if p.household_notes:
        merged["household_notes"] = list(profile.get("household_notes") or []) + p.household_notes
        changed = True
    if p.cooking_frequency:
        merged["cooking_frequency"] = p.cooking_frequency
        changed = True
    if p.favorite_foods:
        merged["favorite_foods"] = db_client.merge_list_field(profile.get("favorite_foods"), p.favorite_foods)
        changed = True
    if p.usual_order_platform:
        merged["usual_order_platform"] = p.usual_order_platform
        changed = True
    if p.health_notes:
        merged["health_notes"] = db_client.merge_list_field(profile.get("health_notes"), p.health_notes)
        changed = True
    if p.inconveniences:
        merged["inconveniences"] = db_client.merge_list_field(profile.get("inconveniences"), p.inconveniences)
        changed = True
    if p.additional_signals:
        existing = profile.get("additional_signals") or []
        merged["additional_signals"] = existing + [s.model_dump() for s in p.additional_signals]
        changed = True

    if mark_onboarded and not profile.get("onboarded_at"):
        merged["onboarded_at"] = datetime.now(timezone.utc).isoformat()
        changed = True

    if not changed:
        return

    db_client.save_profile(user_id, merged)
    agent_logger.log(
        f"[smalltalk_agent] profile 갱신 | preferred_name={result.preferred_name} "
        f"allergens+={result.new_allergens} "
        f"diet+={result.new_diet_restrictions} "
        f"profile+={p.model_dump(exclude_defaults=True)}"
    )


_FALLBACK_GREETING = "안녕하세요! 오늘은 뭘 도와드릴까요?"
_FALLBACK_CHAT = "그렇군요! 필요하신 거 있으면 말씀해 주세요."


def _degraded_smalltalk_result(
    failure_class: FailureClass,
    exc: BaseException,
    is_first_greeting: bool,
    onboarding_started_at: Optional[str],
) -> dict:
    # 온보딩 첫 턴 실패 시 onboarded_at을 안 찍는다 — LLM 실패로 선호도
    # 추출 자체가 안 됐으므로, 다음 세션에서 온보딩을 다시 시도할 수 있게 둔다.
    # 일반 잡담 턴 실패는 애초에 onboarded_at을 안 건드리는 경로라 해당 없음.
    # onboarding_started_at은 실패 턴에도 그대로 들고 가야 다음 턴에 제한시간
    # 계산이 끊기지 않는다.
    fallback = _FALLBACK_GREETING if is_first_greeting else _FALLBACK_CHAT
    return {
        "explanation": fallback,
        "immediate_response": fallback,
        "pending_action": None,
        "stage": "idle",
        "last_agent": "smalltalk_agent",
        "error": None,
        "degraded_mode": True,
        "failure_stage": "smalltalk_llm",
        "degradation_reason": f"{failure_class.value}:{type(exc).__name__}",
        "onboarding_started_at": onboarding_started_at,
    }


def smalltalk_error_handler(state: ShoppingState, error: NodeError) -> Command:
    """NODE_RETRY_POLICY 소진(TRANSIENT_TECHNICAL) 또는 재시도 대상이 아닌 예외
    (PERMANENT_TECHNICAL) 모두 여기로 온다."""
    fc = classify_failure(error.error)
    if fc is FailureClass.TRANSIENT_TECHNICAL:
        agent_logger.log_retry_exhausted(node="smalltalk_agent", exception_type=type(error.error).__name__)
    else:
        agent_logger.log_permanent_technical_error(node="smalltalk_agent", exception_type=type(error.error).__name__)
    is_first_greeting = len(state.get("messages") or []) <= 1
    onboarding_started_at = state.get("onboarding_started_at") or datetime.now(timezone.utc).isoformat()
    return Command(
        update=_degraded_smalltalk_result(fc, error.error, is_first_greeting, onboarding_started_at),
        goto="respond",
    )


def smalltalk_agent_node(state: SmalltalkAgentInput, runtime: Runtime | None = None) -> SmalltalkAgentUpdate:
    # runtime은 그래프 실행 시 LangGraph가 자동 주입한다. 그래프 밖에서 직접
    # 호출할 때는 None이 들어오므로 기본값을 둔다.
    user_id = state.get("user_id", "")
    messages = state.get("messages") or []
    user_input = _extract_user_input(state)

    node_attempt = runtime.execution_info.node_attempt if runtime and runtime.execution_info else 1
    if node_attempt > 1:
        agent_logger.log_retry_attempt_started(node="smalltalk_agent", node_attempt=node_attempt)

    is_first_greeting = len(messages) <= 1
    user_turns = _count_user_turns(messages)

    if is_first_greeting:
        onboarding_started_at = datetime.now(timezone.utc).isoformat()
        elapsed_minutes = 0.0
        agent_logger.log(f"[smalltalk_agent] 진입 | user_id={user_id} (온보딩 1턴째, 인사)")
        prompt = SMALLTALK_GREETING_PROMPT.format(
            profile_field_guide=SMALLTALK_PROFILE_FIELD_GUIDE,
            order_handoff_rule=SMALLTALK_ORDER_HANDOFF_RULE,
            user_input=user_input or "없음",
        )
        past_cap = False
    else:
        # 실패 턴(_degraded_smalltalk_result)도 onboarding_started_at을 들고
        # 가지만, 혹시 비어있으면(예: 과거 세션 데이터) 지금 시각으로 방어적 보정.
        onboarding_started_at = state.get("onboarding_started_at") or datetime.now(timezone.utc).isoformat()
        elapsed_minutes = _onboarding_elapsed_minutes(onboarding_started_at)
        past_cap = elapsed_minutes >= _MAX_ONBOARDING_MINUTES
        agent_logger.log(f"[smalltalk_agent] 진입 | user_id={user_id} (온보딩 {user_turns}턴째, {elapsed_minutes:.1f}분 경과)")
        conversation_so_far = _format_conversation(messages[:-1]) or "(없음)"
        collected_so_far = format_smalltalk_profile(db_client.get_profile(user_id))
        prompt = SMALLTALK_CHAT_PROMPT.format(
            profile_field_guide=SMALLTALK_PROFILE_FIELD_GUIDE,
            topic_guide=SMALLTALK_TOPIC_GUIDE,
            order_handoff_rule=SMALLTALK_ORDER_HANDOFF_RULE,
            collected_so_far=collected_so_far,
            wrap_up_instruction=_WRAP_UP_INSTRUCTION if past_cap else "",
            conversation_so_far=conversation_so_far,
            user_input=user_input or "없음",
        )

    try:
        result = _get_llm().with_structured_output(SmalltalkOutput, method="json_schema").invoke(
            [HumanMessage(content=prompt)]
        )
        if not isinstance(result, SmalltalkOutput):
            raise ValueError("structured output 파싱 실패")
    except Exception as e:
        fc = classify_failure(e)
        agent_logger.log(f"[smalltalk_agent] 생성 실패({fc.value}), fallback: {e}")
        if fc is FailureClass.TRANSIENT_TECHNICAL:
            agent_logger.log_transient_failure(node="smalltalk_agent", node_attempt=node_attempt, exception_type=type(e).__name__)
            raise  # NODE_RETRY_POLICY가 노드 재실행, 소진되면 smalltalk_error_handler로 이동
        return _degraded_smalltalk_result(fc, e, is_first_greeting, onboarding_started_at)

    onboarding_complete = result.onboarding_complete
    if past_cap and not onboarding_complete:
        # wrap_up_instruction을 받고도 LLM이 안 끝낸 예외 상황에서만 개입한다
        # (정상 경로는 위 지시를 받은 LLM이 스스로 true를 반환하고 마무리 인사를
        # 함께 내놓는 것 — reply는 그대로 두고 회계만 강제로 닫는다).
        agent_logger.log(f"[smalltalk_agent] 온보딩 제한시간({_MAX_ONBOARDING_MINUTES}분) 도달했는데도 LLM이 안 끝냄 — 강제 종료")
        onboarding_complete = True

    _merge_profile_signals(user_id, result, mark_onboarded=onboarding_complete)
    agent_logger.log(f"[smalltalk_agent] 응답: {result.reply} (onboarding_complete={onboarding_complete})")

    return {
        "explanation": result.reply,
        "immediate_response": result.reply,
        "pending_action": None,
        "onboarding_started_at": None if onboarding_complete else onboarding_started_at,
        "stage": "idle",
        "last_agent": "smalltalk_agent",
        "error": None,
    }
