"""
Smalltalk Agent Node.

역할: 신규유저(구매이력 0건) 첫 턴에 쇼핑 라우팅 대신 가벼운 온보딩
인사를 건네고, 첫 발화에서 캐치되는 지속성 정보(알레르기/식이제약/
가족구성 등)를 profile에 저장한다.

지금은 intent_agent가 "세션 첫 턴 + 신규유저" 조건을 감지해
intent="smalltalk"로 넘긴 경우에만 도달한다 (routing_map 경유).
대화 중간의 일반 잡담 라우팅은 범위 밖 — 필요해지면 별도 트리거로
확장 예정.
"""
from pydantic import BaseModel, Field
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from configs.llm_config import get_llm
from src.state.schema import ShoppingState
from src.prompts.smalltalk_prompt import SMALLTALK_GREETING_PROMPT
from src.tools import db_client
from src.utils.agent_logger import agent_logger


class ProfileSignalUpdate(BaseModel):
    """첫 발화에서 캐치된 지속성 정보. 감지 안 되면 전부 빈 값."""
    new_allergens: list[str] = Field(default_factory=list)
    new_diet_restrictions: list[str] = Field(default_factory=list)
    general_notes: list[str] = Field(default_factory=list)


class SmalltalkOutput(BaseModel):
    reply: str
    profile_signals: ProfileSignalUpdate = Field(default_factory=ProfileSignalUpdate)


_llm: BaseChatModel | None = None


def _get_llm() -> BaseChatModel:
    global _llm
    if _llm is None:
        _llm = get_llm("context", temperature=0.3, max_tokens=200)
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


def _merge_profile_signals(user_id: str, signals: ProfileSignalUpdate) -> None:
    if not (signals.new_allergens or signals.new_diet_restrictions or signals.general_notes):
        return
    profile = db_client.get_profile(user_id) or {}
    merged = dict(profile)
    merged["allergens"] = sorted(set(profile.get("allergens") or []) | set(signals.new_allergens))
    merged["diet_restrictions"] = sorted(
        set(profile.get("diet_restrictions") or []) | set(signals.new_diet_restrictions)
    )
    if signals.general_notes:
        merged["general_notes"] = list(profile.get("general_notes") or []) + signals.general_notes
    db_client.save_profile(user_id, merged)
    agent_logger.log(
        f"[smalltalk_agent] profile 갱신 | allergens+={signals.new_allergens} "
        f"diet+={signals.new_diet_restrictions} notes+={signals.general_notes}"
    )


def smalltalk_agent_node(state: ShoppingState) -> dict:
    user_id = state.get("user_id", "")
    user_input = _extract_user_input(state)

    agent_logger.log(f"[smalltalk_agent] 진입 | user_id={user_id} (신규유저 첫 턴)")

    try:
        prompt = SMALLTALK_GREETING_PROMPT.format(user_input=user_input or "없음")
        result = _get_llm().with_structured_output(SmalltalkOutput, method="json_schema").invoke(
            [HumanMessage(content=prompt)]
        )
        if not isinstance(result, SmalltalkOutput):
            raise ValueError("structured output 파싱 실패")
    except Exception as e:
        agent_logger.log(f"[smalltalk_agent] 생성 실패, fallback: {e}")
        return {
            "explanation": "안녕하세요! 오늘은 뭘 도와드릴까요?",
            "immediate_response": "안녕하세요! 오늘은 뭘 도와드릴까요?",
            "pending_action": None,
            "stage": "idle",
            "last_agent": "smalltalk_agent",
            "error": None,
        }

    _merge_profile_signals(user_id, result.profile_signals)
    agent_logger.log(f"[smalltalk_agent] 인사: {result.reply}")

    return {
        "explanation": result.reply,
        "immediate_response": result.reply,
        "pending_action": None,
        "stage": "idle",
        "last_agent": "smalltalk_agent",
        "error": None,
    }
