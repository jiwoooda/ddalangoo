"""
Profile Top-up — 공용 "프로필 이어 묻기" 부품.

이미 smalltalk_agent(온보딩)를 거친 사용자라도 11개 프로필 필드를 다 채우고
끝나는 건 아니다(필수 4개만 채워지면 온보딩 종료). 사용자가 그냥 대화를
원할 때, 온보딩 때 못 물어본 나머지 필드를 자연스럽게 이어 묻는다.

트리거(언제 불릴지)를 모른다 — fallback_orchestrator의 chat 분기가 지금
쓰고 있다(satisfaction_checkin.py와 같은 자리, 우선순위만 뒤).

**smalltalk_agent와 데이터 모델을 공유한다** — 톤(SMALLTALK_CHARACTER)뿐 아니라
프로필 스키마(SmalltalkProfileSchema)와 병합 로직(_build_merged_profile)까지
그대로 재사용한다. 여기서 새로 추출한 값이 온보딩 때 쓰던 것과 다른 형태로
쌓이면 나중에 어긋나기 때문이다. 재사용 안 하는 것은 온보딩 전용 상태
관리(consecutive_question_turns/already_asked_topics/onboarding_complete
게이트)뿐이다 — 이번 대화는 그 상태기계와 무관한 한 턴짜리 사이드 대화라서.
"""
from typing import Any, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from configs.llm_config import get_llm
from src.prompts.smalltalk_prompt import SMALLTALK_CHARACTER, SMALLTALK_PROFILE_FIELD_GUIDE
from src.prompts.profile_topup_prompt import PROFILE_TOPUP_ASK_PROMPT, PROFILE_TOPUP_CAPTURE_PROMPT
from src.state.smalltalk_schema import SmalltalkProfileSchema, SMALLTALK_PROFILE_FIELDS, format_smalltalk_profile
from src.agents.smalltalk_agent import SmalltalkOutput, _build_merged_profile
from src.tools import db_client
from src.utils.agent_logger import agent_logger
from src.utils.retry import retry_call

# additional_signals는 "하나 골라서 되물을 단일 필드"가 아니라 자유 형식
# 캐치올이라 이 로테이션 대상에서 제외한다.
_PICKABLE_FIELDS = tuple(f for f in SMALLTALK_PROFILE_FIELDS if f != "additional_signals")

_FIELD_QUESTION_HINT = {
    "food_dislikes": "못 먹거나 싫어하는 음식",
    "value_priority": "가성비 vs 품질·브랜드 중 뭘 더 중요하게 여기는지",
    "delivery_priority": "배송 속도 vs 배송비 절약 중 뭘 더 중요하게 여기는지",
    "household_size": "가구 인원수",
    "household_notes": "가족구성/동거인",
    "cooking_frequency": "직접 요리를 자주 하는지",
    "favorite_foods": "좋아하는 음식",
    "usual_order_platform": "평소 어디서 장을 보는지",
    "health_notes": "건강 관련 신경 쓰이는 부분",
    "inconveniences": "장보기/배달에서 불편했던 점",
}


class ProfileTopupAskOutput(BaseModel):
    reply: str = Field(description="자연스러운 대화체 질문 한두 문장.")


class ProfileTopupCaptureOutput(BaseModel):
    reply: str = Field(description="자연스러운 대화체 리액션 한 문장.")
    profile: SmalltalkProfileSchema = Field(default_factory=SmalltalkProfileSchema)


_ask_llm = None
_structured_ask_llm = None
_capture_llm = None
_structured_capture_llm = None


def _get_ask_llm():
    global _ask_llm, _structured_ask_llm
    if _ask_llm is None:
        _ask_llm = get_llm("context", temperature=0.3, max_tokens=150, retry_owner="application")
        _structured_ask_llm = _ask_llm.with_structured_output(ProfileTopupAskOutput)
    return _structured_ask_llm


def _get_capture_llm():
    global _capture_llm, _structured_capture_llm
    if _capture_llm is None:
        _capture_llm = get_llm("context", temperature=0, max_tokens=250, retry_owner="application")
        _structured_capture_llm = _capture_llm.with_structured_output(ProfileTopupCaptureOutput)
    return _structured_capture_llm


def pick_missing_profile_field(user_id: str) -> Optional[str]:
    """온보딩 이후에도 안 채워진 프로필 필드 하나를 고른다(SMALLTALK_PROFILE_FIELDS
    순서 그대로 — 온보딩이 우선순위로 삼던 순서와 동일). 다 채워져 있으면 None."""
    if not user_id:
        return None
    profile = db_client.get_profile(user_id) or {}
    for field in _PICKABLE_FIELDS:
        if not profile.get(field):
            return field
    return None


def start_profile_topup(user_id: str, field: str) -> Optional[dict[str, Any]]:
    """프로필 항목을 이어 묻는 첫 턴. 반환값은 그대로 state["pending_action"]에
    얹으면 되는 dict(payload에 profile_topup 포함). LLM 실패 시 None."""
    profile = db_client.get_profile(user_id) or {}
    prompt = PROFILE_TOPUP_ASK_PROMPT.format(
        persona=SMALLTALK_CHARACTER,
        profile_field_guide=SMALLTALK_PROFILE_FIELD_GUIDE,
        field=f"{field} ({_FIELD_QUESTION_HINT.get(field, field)})",
        known_profile=format_smalltalk_profile(profile),
    )
    try:
        result = retry_call(_get_ask_llm().invoke, [HumanMessage(content=prompt)])
        if not isinstance(result, ProfileTopupAskOutput):
            raise ValueError("structured output 파싱 실패")
    except Exception as e:
        agent_logger.log(f"[profile_topup] 질문 생성 실패, 스킵: {e}")
        return None

    return {
        "type": "clarification",
        "message": result.reply,
        "payload": {"profile_topup": {"field": field, "asked_message": result.reply}},
    }


def capture_profile_topup_answer(user_id: str, pending_check: dict[str, Any], user_text: str) -> str:
    """되물음에 대한 답변 턴. 성공/실패와 무관하게 항상 사용자에게 보여줄
    reply 문자열을 반환한다."""
    prompt = PROFILE_TOPUP_CAPTURE_PROMPT.format(
        persona=SMALLTALK_CHARACTER,
        asked_message=pending_check.get("asked_message", ""),
        user_text=user_text,
        profile_field_guide=SMALLTALK_PROFILE_FIELD_GUIDE,
    )
    try:
        result = retry_call(_get_capture_llm().invoke, [HumanMessage(content=prompt)])
        if not isinstance(result, ProfileTopupCaptureOutput):
            raise ValueError("structured output 파싱 실패")
    except Exception as e:
        agent_logger.log(f"[profile_topup] 답변 해석 실패: {e}")
        return "네, 알겠어요! 말씀해주셔서 감사해요."

    # SmalltalkProfileSchema를 그대로 구조화 출력 스키마로 재사용하면, 그
    # 필드 설명(예: health_notes의 "명확히 없다고 답하면 ['없음']으로")이
    # 이번 턴에 안 물어본 필드에도 적용돼서 LLM이 추측성으로 같이 채우는
    # 사례가 실측으로 나왔다(food_dislikes만 물었는데 health_notes=['없음']이
    # 같이 채워짐). 이번 턴에 실제로 물어본 필드 값만 남기고 나머지는 코드
    # 레벨에서 강제로 비운다 — 프롬프트 지시만으로는 못 막았다.
    asked_field = pending_check.get("field")
    only_asked = SmalltalkProfileSchema(**{asked_field: getattr(result.profile, asked_field)}) if asked_field else SmalltalkProfileSchema()

    try:
        # smalltalk_agent의 병합 로직을 그대로 재사용 — 온보딩 때와 나중에
        # 이어 채울 때 프로필 데이터 형태가 갈라지지 않게 하기 위함.
        wrapped = SmalltalkOutput(reply=result.reply, profile=only_asked)
        merged, changed = _build_merged_profile(user_id, wrapped)
        if changed:
            db_client.save_profile(user_id, merged)
            agent_logger.log(f"[profile_topup] 프로필 갱신 완료 user_id={user_id} field={pending_check.get('field')}")
    except Exception as e:
        agent_logger.log(f"[profile_topup] 프로필 저장 실패: {e}")

    return result.reply
