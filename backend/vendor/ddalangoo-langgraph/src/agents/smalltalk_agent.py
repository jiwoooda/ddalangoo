"""
Smalltalk Agent Node.

역할: 신규유저(구매이력 0건, 미온보딩) 진입 시 코드 레벨 게이트
(src/graph/router.py의 route_entry)가 intent_agent를 거치지 않고 바로 이
노드로 라우팅한다 — smalltalk는 LLM이 매 턴 판단하는 intent가 아니라, 신규유저
진입 시 자동으로 시작되는 온보딩 이벤트다.

온보딩은 한 턴짜리 인사로 끝날 수도, 여러 턴에 걸친 대화로 이어질 수도 있다.
11개 profile 필드는 "캐물어야 할 체크리스트"가 아니라 자연스러운 대화의
결과로 따라오는 부산물이다(SMALLTALK_PERSONA) — 그래서 LLM이 스스로 반환한
onboarding_complete를 무조건 신뢰하지 않고, check_completion_gate로 이중
검증한다: REQUIRED_FIELDS(food_dislikes/delivery_priority/household_size/
value_priority) 4개 중 _REQUIRED_FIELD_MIN_FILLED(3)개 이상 채워졌을 때만
LLM의 종료 판단을 그대로 받아들이고, 아니면 false로 override해서 대화를
한 턴 더 이어간다(4개를 다 요구했더니 애매한 발화 하나 때문에 자연 완료가
거의 안 열리는 문제가 실측으로 확인돼서 완화함). 예외 둘 — 타임아웃(무한루프
방지)과 주문 핸드오프(사용자가 명확한 구매 요청을 했을 때, 정보 수집보다
요청 처리가 우선)는 필드 미충족이어도 즉시 종료를 허용한다.

대화가 너무 길어지는 걸 막는 안전장치로 온보딩 시작 시각
(state.onboarding_started_at, 1턴째에 기록)부터 _MAX_ONBOARDING_MINUTES가
지나면, LLM에게 이번 턴엔 자연스럽게 마무리해달라고 프롬프트로 미리
안내한다(get_wrap_up_instruction — 타임아웃 종료와 필드충족에 의한 자연
종료는 톤이 다른 별도 문구를 쓴다). 음성 대화라 턴 수만으론 실제 경과
시간을 가늠할 수 없어 턴 수 대신 시각을 쓴다.

화제(무엇을 알아야 하는가)와 화법(어떻게 물을 것인가)을 분리한다 — 화제는
SMALLTALK_TOPIC_GUIDE/collected_so_far가 계속 담당하고, 화법은 매 턴
select_style_pattern이 SMALLTALK_STYLE_PATTERNS 중 최근 2~3턴에 안 쓴
것으로 로테이션해서 설문조사 느낌을 없앤다(state.recent_patterns_used에
기록).

이 노드는 "구조화된 수집기"다 — SmalltalkProfileSchema를 채워 profile에
누적 저장할 뿐, soft_preference/explicit_exclusion 같은 tier 분류는 하지
않는다. tier 분류는 context_agent가 이 profile 데이터를 읽어서 담당한다
(context_agent.build_preference_context 참고).
"""
import random
import re
from difflib import SequenceMatcher
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
    SMALLTALK_EPISODE_BANK,
    SMALLTALK_GREETING_FLOW_KNOWN_NAME,
    SMALLTALK_GREETING_FLOW_UNKNOWN_NAME,
    SMALLTALK_GREETING_PROMPT,
    SMALLTALK_NAME_GREETING_HINT,
    SMALLTALK_ORDER_HANDOFF_RULE,
    SMALLTALK_PERSONA,
    SMALLTALK_PROFILE_FIELD_GUIDE,
    SMALLTALK_SAFETY_FIELD_NOTE,
    SMALLTALK_STYLE_PATTERNS,
    SMALLTALK_TOPIC_GUIDE,
    SMALLTALK_TOPIC_PIVOT_HINT,
)
from src.tools import db_client
from src.utils.agent_logger import agent_logger
from src.utils.retry import FailureClass, classify_failure

# check_completion_gate의 주문-핸드오프 예외 판단용. 처음엔 route_entry의
# _looks_like_order_request_fallback을 그대로 재사용했는데, 그 함수는
# reorder 신호("저번에"/"지난번에" 등)까지 포함해서 상품명 문맥과 무관하게
# 매칭된다(intent_agent._should_force_reorder는 이 신호를 상품 키워드와
# AND로 묶어 쓰지만, 이 폴백 함수 자체엔 그런 결합이 없다) — 스몰톡엔 구매
# 이력/상품 키워드 문맥이 아예 없어서, "저번에 건강검진 갔는데 당뇨라던데"
# 같은 순수 회상 발화까지 재주문 요청으로 오판해 is_order_handoff가 True가
# 되고, check_completion_gate가 필수 필드나 건강 후속 확인 여부와 무관하게
# 즉시 온보딩을 끝내버리는 문제가 실측으로 확인됐다(당뇨 언급 직후 바로
# 종료). 스몰톡의 SMALLTALK_ORDER_HANDOFF_RULE은 애초에 "우유 사줘"류의
# 명확한 구매 요청만 다루므로, 아래는 그 구매 동사만 본다 — 모호한 reorder
# 신호는 아예 제외한다.
_SMALLTALK_ORDER_TRIGGERS = (
    "사줘", "사줄래", "사주세요", "구매해", "구매해줘", "주문해",
    "사고싶어", "사고 싶어", "사 줘",
)


def _looks_like_explicit_order_request(user_input: str) -> bool:
    return any(t in user_input for t in _SMALLTALK_ORDER_TRIGGERS)


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
    asked_topic_field: Optional[str] = Field(
        default=None,
        description="reply에 질문(물음표든 암묵적 '궁금해요'든)이 있다면, 그 질문이 어떤 "
        "profile 필드에 대한 것인지 정확한 필드명으로: favorite_foods, food_dislikes, "
        "usual_order_platform, inconveniences, health_notes, household_size, "
        "value_priority, delivery_priority, cooking_frequency, preferred_name. profile "
        "필드와 무관한 안부성 질문(예: '식사는 하셨어요?')이면 meal_check. 질문이 "
        "없었다면 null. 화제 반복 방지를 위해 코드가 이 값으로 추적하므로, 실제로 어떤 "
        "내용을 물었는지와 정확히 일치해야 한다(예: 좋아하는 음식을 물었으면 반드시 "
        "favorite_foods, 다른 값을 쓰면 안 됨). 리액션에 자연스럽게 얹힌 감탄형/수사적 "
        "질문(예: '그럼 다음엔 또 뭘 드실지 궁금해지네요')처럼 실제로 그 정보를 알아내려는 "
        "목적이 아니면 null로 두세요 — 진짜로 답을 듣고 싶어서 묻는 질문일 때만 채우세요.",
    )


_MAX_ONBOARDING_MINUTES = 20

_WRAP_UP_INSTRUCTION_NATURAL = """\
# ⚠️ 지금은 마무리 턴입니다 — 아래 규칙이 다른 모든 지시보다 우선합니다

규칙 1. reply에 물음표(?)를 절대 쓰지 마세요. 질문 금지, 서술형 문장으로만
끝내세요. 위에서 고른 화법 예시나 턴 구조 지시가 질문을 요구해도 무시하세요.
규칙 2. onboarding_complete=true로 설정하세요.
규칙 3. 아래 "지금까지의 대화"에서 딸랑구가 직전 1~2턴에 이미 썼던 표현이나
리액션을 그대로 재사용하지 마세요 — 마무리 멘트는 새로운 문장이어야 합니다.

reply는 아래 틀을 그대로 참고해서, 지금까지 나온 이야기에 맞게 자연스럽게
바꿔서 쓰세요(여운이 남게, 조금 정성스럽게):
"(방금 나온 이야기 한두 가지에 대한 짧은 공감 한마디). 앞으로 필요한 거
있으면 '우유 사줘'처럼 편하게 말씀만 해주세요, 제가 바로 챙겨드릴게요."

"이제 도와드릴게요" 같은 업무 인계 톤이 아니라 딸랑구 캐릭터 톤을 유지하고,
"그만하겠습니다" 식으로 뚝 끊지 말고 이 흐름 그대로 자연스럽게 마무리하세요.
"""

_WRAP_UP_INSTRUCTION_TIMEOUT = """\
# ⚠️ 지금은 마무리 턴입니다 — 아래 규칙이 다른 모든 지시보다 우선합니다

규칙 1. reply에 물음표(?)를 절대 쓰지 마세요. 질문 금지, 서술형 문장으로만
끝내세요. 위에서 고른 화법 예시나 턴 구조 지시가 질문을 요구해도 무시하세요.
규칙 2. onboarding_complete=true로 설정하세요.
규칙 3. 아래 "지금까지의 대화"에서 딸랑구가 직전 1~2턴에 이미 썼던 표현이나
리액션을 그대로 재사용하지 마세요 — 마무리 멘트는 새로운 문장이어야 합니다.

reply는 아래 틀을 그대로 참고해서, 지금까지 나온 이야기에 맞게 자연스럽게
바꿔서 쓰세요(아쉬운 티 내지 말고 가볍게, NATURAL 종료보다 담백하게):
"(가볍게 한마디로 대화 정리). 다음에 또 얘기해요, 필요한 거 있으면 '우유
사줘'처럼 편하게 말씀만 해주시고요."

"이제 도와드릴게요" 같은 업무 인계 톤이 아니라 딸랑구 캐릭터 톤을 유지하고,
뚝 끊지 말고 이 흐름 그대로 자연스럽게 마무리하세요.
"""

# 마무리 트리거가 된 발화가 "네"/"맞아요" 같은 짧은 맞장구일 때(is_thin_reply)
# 추가되는 조각 — 위 두 템플릿 모두 "방금 나온 이야기"를 반영하라고 하는데,
# 맞장구 자체엔 반영할 내용이 없어서 모델이 직전 봇 발화(질문)의 소재를
# 억지로 다시 꺼내 "~궁금해요"처럼 물음표 없는 암묵적 질문을 던지고 바로
# 마무리 문장을 붙이는 부자연스러운 패턴이 실측에서 나왔다(B-5는 리터럴
# "?"만 잘라내므로 이 경우를 못 잡는다).
_WRAP_UP_THIN_REPLY_ADDENDUM = """
규칙 4. 방금 사용자 발화는 "네", "맞아요" 같은 짧은 맞장구라 새로 나온
이야기가 없습니다. 이걸 억지로 반영하려 하지 말고, 지금까지의 대화 전체
에서 인상 깊었던 것 한두 가지를 골라 마무리 인사에 자연스럽게 녹이세요.
"궁금해요", "~는지 궁금하네요"처럼 물음표 없이도 답을 기다리는 듯한
표현은 물음표만큼 피하세요 — 끝까지 완전한 평서문으로 마무리하세요.
"""

# 최근 이만큼 연속으로 "정보요청형" 질문이 나왔으면, 다음 턴은 질문을
# 강제로 생략시킨다 — "질문 없는 턴도 괜찮다"는 권장 문구만으론 실측에서
# 매 턴 질문이 반복됐다(8턴 전부 물음표로 끝남). 처음엔 물음표 유무만
# 봤는데, "그럼 다음엔 또 뭘 드실지 궁금해지네요"처럼 리액션에 자연스럽게
# 얹힌 감탄형 질문까지 똑같이 카운트되면서, 실제로는 자연스럽게 이어가도
# 되는 턴까지 억지로 평서문으로 끊어버리는 부작용이 있었다(사용자가 "할
# 말이 없어진다"고 지적) — 그래서 카운트 대상을 asked_topic_field가 실제
# 데이터 수집 필드일 때(_TRACKED_TOPIC_FIELDS에서 meal_check 제외 — 안부성
# 질문이라 정보요청이 아님)로 좁혔다. 임계치 자체는 그대로 둔다: 이제
# "정보요청형 질문 3연속"만 의미하므로 완화할 필요가 없다.
_MAX_CONSECUTIVE_QUESTION_TURNS = 3

# turns_without_progress(화제 정체 카운터)가 이 값 이상으로 극단적으로
# 쌓이면, 정보요청형 질문 카운트와 무관하게 질문 억제를 강제한다 — 화제
# 정체 강제개입(_TOPIC_STALL_TURN_THRESHOLD + _TOPIC_STALL_FORCE_AFTER_
# IGNORED_TURNS = 4턴)까지 시도했는데도 안 풀리는 최후의 안전판. 정보요청형
# 카운트를 좁힌 뒤에도 "필수 아닌 화제를 계속 캐묻는데 정체 카운터는 안
# 오르는" 경우처럼 서로 다른 실패 모드를 잡으므로, 하나로 합치지 않고
# OR로 결합한다.
_QUESTION_SUPPRESSION_STALL_SAFETY_NET = 8

# wrap-up과 같은 원리: 화법 few-shot 예시가 질문으로 끝나므로, 억제 문구를
# "우선한다"고 덧붙이는 것만으론 못 이긴다(실측 확인됨) — 그래서 이번
# 턴엔 화법 예시 자체를 이 문구로 완전히 교체해서 경쟁 신호를 없앤다.
_QUESTION_SUPPRESSION_STYLE_OVERRIDE = """\
(이번 턴은 질문을 연속으로 너무 많이 해서, 화법 예시 대신 이 지시를
따르세요: reply에 물음표(?)를 쓰지 말고, 리액션과 공감 또는 짧은 자기
얘기만으로 자연스럽게 마무리하세요. 질문은 다음 턴에 다시 해도 됩니다.)
"""

# 화법 예시 교체만으로는 부족했다(실측 확인 — "# 턴 구조" 섹션이 질문을
# "선택"으로 언급해서 상쇄됨) — wrap_up_instruction과 같은 늦은 위치(입력
# 직전)에 같은 "규칙이 우선한다" 포맷의 강한 지시를 추가로 둬서 이중으로
# 막는다.
_QUESTION_SUPPRESSION_INSTRUCTION = """\
# ⚠️ 이번 턴은 질문 금지입니다 — 아래 규칙이 다른 모든 지시보다 우선합니다
방금 전까지 질문이 여러 턴 연속으로 이어졌습니다.
규칙 1. reply에 물음표(?)를 절대 쓰지 마세요. 위 턴 구조나 화법 지시가
질문을 언급해도 무시하세요.
규칙 2. 리액션·공감이나 짧은 자기 얘기만으로 자연스럽게 끝내세요.
질문은 다음 턴에 다시 해도 되니 이번 턴만 참으세요.

reply는 아래 틀을 그대로 참고해서, 지금까지 나온 이야기에 맞게 자연스럽게
바꿔서 쓰세요(이 틀에는 물음표가 없다는 걸 확인하고, 그대로 물음표 없이
마무리하세요):
"(방금 나온 이야기에 대한 공감/리액션 한두 문장). (이번 턴 자기 얘기
소재를 반영한 한 문장, 마지막은 평서문으로.)"
"""

# 필수로 채워지길 기대하는 필드 — 이 중 일정 비율 이상 안 채워졌으면 LLM이
# onboarding_complete=true를 반환해도 check_completion_gate가 override한다
# (타임아웃/주문 핸드오프는 예외).
REQUIRED_FIELDS = {"food_dislikes", "delivery_priority", "household_size", "value_priority"}

# 4개를 전부 다 채워야만 완료를 허용했더니, "자극적인 건 피하려고 해요" 같은
# 애매한 발화가 health_notes로만 분류되고 food_dislikes엔 끝까지 안 들어가는
# 케이스에서 자연 완료가 실측으로 거의 안 열렸다(항상 타임아웃까지 감) —
# 그래서 80~90%만 채워져도 마무리하도록 완화했다. 4개뿐이라 정확히
# 80~90%를 만들 수는 없어(3/4=75%, 4/4=100%), 가장 가까운 정수 임계치인
# "4개 중 3개 이상"을 채택했다.
_REQUIRED_FIELD_MIN_FILLED = 3


def _required_fields_filled(profile: dict) -> bool:
    filled = sum(1 for f in REQUIRED_FIELDS if profile.get(f) not in (None, [], ""))
    return filled >= _REQUIRED_FIELD_MIN_FILLED


def _required_fields_filled_count(profile: dict) -> int:
    return sum(1 for f in REQUIRED_FIELDS if profile.get(f) not in (None, [], ""))


# 화제 정체 감지용 — "필수 항목을 우선 고려하라"는 SMALLTALK_TOPIC_GUIDE의
# 추상 지시가 "방금 나온 이야기에서 파생되는 화제로 이어가라"는 훨씬 강한
# 지시에 실측에서 매번 졌다(예: 음식 얘기가 소스→다른 음료로 몇 턴이고
# 계속 파생되기만 하고 REQUIRED_FIELDS는 하나도 안 채워짐). 그래서 몇 턴
# 연속으로 필수 필드 진행이 없으면 코드가 감지해서, 필드별 구체적 전환
# 예시로 강제 전환한다 — 짧은 맞장구 전용이던 SMALLTALK_TOPIC_PIVOT_HINT도
# 같은 이유(추상적이라 예시가 없음)로 실패했으므로 이 메커니즘이 대체한다.
_TOPIC_STALL_TURN_THRESHOLD = 2

# 프롬프트 지시(_TOPIC_STALL_TURN_THRESHOLD)만으로는 부족했다 — 실측에서
# "화제 정체 N턴 연속" 로그가 8턴 넘게 연속으로 찍히는데도 매번 무관한
# 화제(카페→빵→고기굽기→음료)로 계속 새는 케이스가 확인됐다(household_size로
# 전환하라는 예시 문장을 그대로 줬는데도 단 한 번도 안 물어봄). 소프트
# 지시가 이만큼(_TOPIC_STALL_TURN_THRESHOLD 이후 추가로 이만큼 더) 연속
# 무시되면, B-5와 같은 원리로 코드가 reply를 직접 고쳐서 지정된 필드
# 질문을 강제로 붙인다 — "규칙이 우선한다"는 지시조차 안 먹히는 경우의
# 마지막 수단.
_TOPIC_STALL_FORCE_AFTER_IGNORED_TURNS = 2

_REQUIRED_FIELD_PRIORITY = ["household_size", "delivery_priority", "value_priority", "food_dislikes"]

_REQUIRED_FIELD_PIVOT_EXAMPLES = {
    "household_size": '"그러고 보니 궁금한 게 있는데, 지금 혼자 지내세요 아니면 같이 사시는 분이 계세요?"',
    "delivery_priority": '"문득 궁금한데, 배송은 빠른 게 좋으세요 아니면 배송비 아끼는 게 더 좋으세요?"',
    "value_priority": '"그런데 궁금한 게, 물건 고르실 때 가격을 더 보시는 편이세요 아니면 품질을 더 보시는 편이세요?"',
    "food_dislikes": '"혹시 못 드시거나 안 좋아하시는 음식도 있으세요?"',
}


def _topic_stall_target_field(merged_profile: dict, stalled_turns: int = 0) -> Optional[str]:
    """화제 전환 대상으로 삼을, 아직 안 채워진 필수 필드 하나. 채울 필드가
    이미 다 있으면(정체가 문제 안 됨) None.

    stalled_turns로 미충족 필드 목록을 순환시킨다(고정적으로 항상
    missing[0]만 쓰지 않음) — 사용자가 그 질문에 답을 안(또는 회피)하는
    채로 정체가 계속되면, 매번 우선순위 1번 필드로만 강제 전환하다가는
    같은 질문을 무한 반복하게 된다(force_topic_pivot_reply가 지시 무시
    누적 시 이 값으로 reply를 직접 고쳐 쓰므로 특히 중요). 그래서 정체가
    길어질수록 다음 미충족 필드로 옮겨가며 최소 한 번씩은 골고루 물어보게
    한다."""
    missing = [f for f in _REQUIRED_FIELD_PRIORITY if merged_profile.get(f) in (None, [], "")]
    if not missing:
        return None
    return missing[stalled_turns // _TOPIC_STALL_TURN_THRESHOLD % len(missing)]


def get_topic_stall_instruction(merged_profile: dict, stalled_turns: int = 0) -> str:
    """대화가 같은 화제에 머물러 REQUIRED_FIELDS 진행이 없을 때 호출한다.
    채울 필드가 이미 다 있으면(정체가 문제 안 됨) 빈 문자열."""
    target = _topic_stall_target_field(merged_profile, stalled_turns)
    if not target:
        return ""
    example = _REQUIRED_FIELD_PIVOT_EXAMPLES[target]
    return f"""
# ⚠️ 화제 전환이 필요합니다 — 아래 규칙이 다른 모든 지시보다 우선합니다
규칙 1. 지금까지 대화가 같은 화제에 여러 턴째 머물러 있습니다. 이번 턴은
지금 화제(예: 방금 나온 음식의 세부사항)를 절대 더 파고들지 마세요.
규칙 2. 다른 새 화제도 아니고 정확히 아래 예시가 묻는 내용으로 전환하세요
— 위 화제 가이드의 다른 항목(예: 장보는 곳)으로 임의로 대체하면 안 됩니다.
방금 나온 이야기를 짧게 리액션한 뒤, 아래 예시를 그대로 참고해서 자연스럽게
이으세요("그러고 보니", "문득 궁금한데" 같은 전환어를 쓰면 자연스럽습니다):
{example}
"""


def force_topic_pivot_reply(reply: str, target_field: str) -> str:
    """topic_stall_instruction이 _TOPIC_STALL_FORCE_AFTER_IGNORED_TURNS턴
    넘게 무시됐을 때 쓰는 마지막 수단 — reply에 이미 있던 질문 문장을
    지우고(리액션/공감은 남김) 지정된 필수 필드 질문을 그대로 붙인다."""
    without_question = _limit_questions(reply, max_questions=0).strip()
    pivot_question = _REQUIRED_FIELD_PIVOT_EXAMPLES[target_field].strip('"')
    return f"{without_question} {pivot_question}".strip()


def force_repeat_avoidance_reply(
    reply: str, merged_profile: dict, stalled_turns: int = 0
) -> tuple[str, Optional[str]]:
    """_is_cross_branch_repeat가 감지한 반복을 처리한다 — 미충족 필수
    필드가 있으면 force_topic_pivot_reply로 그쪽으로 돌리고(반환값
    asked_topic_field 갱신용), 없으면 질문만 제거한다."""
    target = _topic_stall_target_field(merged_profile, stalled_turns)
    if target:
        return force_topic_pivot_reply(reply, target), target
    return _limit_questions(reply, max_questions=0), None


def _is_cross_branch_repeat(
    *,
    reply_has_question: bool,
    asked_topic_field: Optional[str],
    already_asked_topics: list[str],
    health_followup_active: bool,
    topic_stall_target: Optional[str],
) -> bool:
    """이번 턴이 어느 브랜치(wrap-up/건강확인/질문억제/이름안부/정상)에서
    처리됐는지와 무관하게, 결과적으로 이미 물었던 화제를 또 물었는지만
    본다 — avoid_repeat_instruction이 브랜치 배타 구조 때문에 정체 턴에는
    아예 안 켜지는 사각지대(필수 필드 4개 밖의 화제)를 결정론적으로 잡는다.
    건강 후속 확인 중엔 health_notes를 2턴 동안 다시 묻는 게 설계된
    동작이라 예외 처리하고, 방금 화제 정체 강제개입이 이미 처리한 필드도
    중복 개입하지 않는다."""
    return (
        reply_has_question
        and asked_topic_field in already_asked_topics
        and not health_followup_active
        and asked_topic_field != topic_stall_target
    )


# 화제 반복 방지 — B-3(already_asked_topics)가 대화 중간 문단에서 "다시
# 묻지 마세요"라고 지시하는 것만으로는 실측에서 매번 무시됐다(같은 질문이
# 3턴 연속 토씨 하나 안 틀리고 반복됨) — wrap-up/질문억제/화제정체와 같은
# 교훈으로, 이것도 후반부 강한 "규칙이 우선한다" 블록으로 옮긴다.
#
# 추가로 "아까 말했잖아" 같은 사용자의 명시적 항의는 코드로 직접 감지해서,
# 화제 키워드 매칭이 못 잡는 반복(예: 표현이 완전히 달라서 already_asked_
# topics에 안 걸린 경우)까지 놓치지 않고 최우선으로 처리한다.
#
# "다니까"/"라니까" 계열도 추가한다 — "마트 간다니까"처럼 "아까 말했잖아"라고
# 명시하진 않지만 이미 답한 걸 짜증 섞어 재확인해주는 어미다. 실측에서
# 이런 발화 뒤에도 딸랑구가 태연히 같은 화제로 또 캐묻는 게 확인됐다(사용자가
# 세 번째 답하는데도 반응 못 함) — "아까 말했잖아"류만큼 명시적이진 않지만
# 짜증/반복 신호로 취급한다.
_FRUSTRATION_PATTERNS = (
    "아까 말했", "아까도 물어", "말했잖", "물어봤잖", "이미 말했", "방금 말했", "몇 번을 말",
    "다니까", "라니까",
)


def detect_frustration(user_input: str) -> bool:
    return any(p in user_input for p in _FRUSTRATION_PATTERNS)


def get_avoid_repeat_instruction(pending_topics: list[str], frustration_detected: bool) -> str:
    """already_asked_topics에 남은 화제나 사용자의 명시적 항의가 있을 때
    호출한다. 둘 다 없으면 빈 문자열."""
    if not pending_topics and not frustration_detected:
        return ""
    display_labels = [_TOPIC_FIELD_DISPLAY_LABEL.get(t, t) for t in pending_topics]
    topics_str = ", ".join(display_labels) if display_labels else "방금 그 화제"
    if frustration_detected:
        return f"""
# ⚠️ 화제 반복 금지 — 아래 규칙이 다른 모든 지시보다 우선합니다
규칙 1. 사용자가 같은 질문이 반복된다고 방금 직접 항의했습니다("아까
말했잖아" 등). 이 화제({topics_str})는 완전히 접으세요 — 사과하듯 짧게
인정만 하고, 다시는 묻지 마세요.
규칙 2. 이번 턴엔 반드시 완전히 새로운 화제로 전환하세요. 방금 사용자가
준 정보에서 자연스럽게 파생되는 질문이면 가장 좋습니다.
"""
    return f"""
# ⚠️ 화제 반복 금지 — 아래 규칙이 다른 모든 지시보다 우선합니다
다음 화제는 이미 물었지만 아직 답을 못 들었습니다: {topics_str}
표현을 바꿔서도, 다른 각도로도 다시 묻지 마세요 — 사용자가 답을 피한
것으로 보고 존중하며, 완전히 다른 화제로 넘어가세요.
"""


# 건강 이슈 심층 탐색 — 당뇨/고혈압 등 의학적 키워드가 사용자 발화에서
# 나오면(다른 화제처럼 한 번 스치고 다음 화제로 넘어가지 않도록) 최소
# 한 턴 더 그 화제를 우선하도록 강제한다. 실측에서 "당뇨라 단 거 못
# 먹는다"는 발화 직후 바로 onboarding_complete=true가 되어, 복용 약이나
# 구체적 식단 제한 같은 후속 확인이 전혀 없이 대화가 끝나버리는 문제가
# 확인됐다 — 건강 정보는 안전(위험 회피)과 직결되는 필드라 얕게 끝나면
# 실질적 위해(예: 단 음식 추천)로 이어질 수 있어, 다른 화제 정체 감지
# (get_topic_stall_instruction)보다 우선순위를 높게 둔다. check_completion_gate
# 에도 별도 파라미터로 넘겨서, 필수 필드가 이미 다 채워졌어도(3/4, 4/4)
# 이 화제가 안 끝났으면 온보딩 완료를 보류한다.
_HEALTH_KEYWORDS = (
    "당뇨", "고혈압", "혈압", "혈당", "알레르기", "알러지", "저염", "신부전",
    "지병", "고지혈", "천식", "통풍", "콩팥", "신장", "위염", "장염",
)

# 최초 감지 턴 이후 몇 턴 더 이 화제를 우선할지. 감지 턴 자체에서 이미
# 후속 질문 하나를 던지므로(get_health_followup_instruction), 여기 1을
# 더해 총 최소 2턴(감지 턴 + 다음 턴)은 건강 화제를 우선하게 된다.
_HEALTH_FOLLOWUP_EXTRA_TURNS = 1


def detect_health_disclosure(user_input: str) -> bool:
    return any(k in user_input for k in _HEALTH_KEYWORDS)


def get_health_followup_instruction(just_disclosed: bool) -> str:
    if just_disclosed:
        return """
# ⚠️ 건강 이슈가 방금 언급됐습니다 — 아래 규칙이 다른 모든 지시보다 우선합니다
규칙 1. 이번 턴은 다른 화제로 넘어가지 마세요. 방금 나온 건강 이슈를 더
구체적으로 확인하는 질문 하나를 하세요 — 예: 그것 때문에 못 드시거나
피해야 하는 음식이 정확히 무엇인지, 복용 중인 약이 있는지, 이미 지키고
계신 식단이 있는지 중 하나.
규칙 2. onboarding_complete는 이번 턴에 true로 설정하지 마세요 — 이
화제를 더 확인해야 합니다.
"""
    return """
# ⚠️ 건강 이슈를 아직 충분히 확인하지 못했습니다 — 아래 규칙이 다른 모든 지시보다 우선합니다
규칙 1. 직전 턴에 나온 건강 이슈(당뇨/고혈압 등)에 대해 아직 안 들은 것
하나만 더 확인하고 넘어가세요 — 못 드시는 음식, 복용 약, 이미 지키는
식단 중 아직 안 나온 게 있으면 그걸 물어보세요. 이미 충분히 들었다면
질문 없이 짧게 그 이야기를 정리하는 리액션만 하세요.
규칙 2. onboarding_complete는 이번 턴에 true로 설정하지 마세요.
"""


# ══════════════════════════════════════════════════════════════════
# 하네스 검증/이관 — 결정론적으로 판별 가능한 것은 프롬프트 지시에만
# 맡기지 않고 코드로 교차검증한다(smalltalk_prompt.py 모듈 docstring의
# "프롬프트 슬리밍 + 하네스 이관" 참고).
# ══════════════════════════════════════════════════════════════════

# B-1: food_dislikes로 잘못 분류되기 쉬운 의학적 제약 키워드. 여기 걸리면
# LLM 판단과 무관하게 new_diet_restrictions 후보로 재분류한다 — 안전
# 배제가 안 걸리면 실제 위해로 이어질 수 있는 지점이라 LLM 판단만 믿지 않는다.
_MEDICAL_FOOD_KEYWORDS = (
    "알레르기", "알러지", "당뇨", "고혈압", "저염", "신부전", "콩팥", "신장",
    "위염", "장염", "천식", "통풍", "고지혈", "먹으면 안", "복용", "처방약",
)


def _reclassify_medical_food_dislikes(food_dislikes: list[str]) -> tuple[list[str], list[str]]:
    """food_dislikes 항목 중 의학적 키워드가 섞여 있으면 diet_restrictions
    후보로 분리한다. 반환값: (그대로 둘 항목, new_diet_restrictions로 승격할 항목)."""
    kept, promoted = [], []
    for item in food_dislikes:
        if any(kw in item for kw in _MEDICAL_FOOD_KEYWORDS):
            promoted.append(item)
        else:
            kept.append(item)
    return kept, promoted


# B-2: 방향성 이분법 필드 교차검증. delivery_priority가 실측에서 정반대로
# 추출된 적이 있어서("배송은 빠른 게 좋아요" → 배송비절약으로 오분류),
# 프롬프트 지시(볼드/매핑 예시)만으로는 재발을 막는다는 보장이 없다고 보고
# 사용자 발화 키워드로 코드가 한 번 더 방향을 확인해 반대면 정정한다.
_DELIVERY_SPEED_KEYWORDS = ("빠른", "빨리", "신속", "급해요", "기다리는 거 싫")
_DELIVERY_COST_KEYWORDS = ("배송비", "무료배송", "천천히 와도", "느려도")
_VALUE_CHEAP_KEYWORDS = ("가성비", "저렴", "싼 게", "가격부터", "할인")
_VALUE_QUALITY_KEYWORDS = ("품질", "브랜드", "좋은 걸로", "비싸도")


def _detect_direction(
    text: str, positive_kws: tuple[str, ...], negative_kws: tuple[str, ...], positive_value: str, negative_value: str
) -> Optional[str]:
    has_pos = any(kw in text for kw in positive_kws)
    has_neg = any(kw in text for kw in negative_kws)
    if has_pos and not has_neg:
        return positive_value
    if has_neg and not has_pos:
        return negative_value
    return None


def _cross_check_directional_fields(profile: SmalltalkProfileSchema, user_input: str) -> list[str]:
    """LLM이 뽑은 delivery_priority/value_priority가 사용자 발화의 키워드
    방향과 반대면 코드가 자동 정정한다. 반환값: 정정된 필드명 목록(로그용)."""
    corrected = []
    detected_delivery = _detect_direction(
        user_input, _DELIVERY_SPEED_KEYWORDS, _DELIVERY_COST_KEYWORDS, "빠른배송", "배송비절약"
    )
    if detected_delivery and profile.delivery_priority and detected_delivery != profile.delivery_priority:
        profile.delivery_priority = detected_delivery
        corrected.append("delivery_priority")

    detected_value = _detect_direction(
        user_input, _VALUE_CHEAP_KEYWORDS, _VALUE_QUALITY_KEYWORDS, "가성비", "품질·브랜드"
    )
    if detected_value and profile.value_priority and detected_value != profile.value_priority:
        profile.value_priority = detected_value
        corrected.append("value_priority")

    return corrected


# B-3: "이미 물었지만 아직 답을 못 들은 화제" 추적. 예전엔 reply 문자열에
# 고정 키워드가 있는지로 화제를 감지했는데, LLM이 매번 다른 어휘로 같은
# 질문을 표현할 수 있어서(예: "즐겨 드시는" 대신 "주로 잡수시는") 첫 질문이
# 감지망을 빠져나가면 already_asked_topics에 아예 안 쌓여 재질문을 못 막는
# 문제가 실측(같은 "좋아하는 음식" 질문이 여러 번, 사용자가 "아까
# 말했잖니"라고 항의)으로 확인됐다 — 완전 일치 문자열 매칭 대신, LLM이 이번
# reply의 질문이 어떤 필드에 대한 것인지 구조화 출력(asked_topic_field)으로
# 직접 보고하게 하고, 코드는 그 값을 그대로 추적한다(해당 필드가 채워지면
# 자동으로 빠짐). "의미 단위" 판단을 LLM에게 맡기고, "이미 물은 화제는
# 다시 안 묻는다"는 결정론적 집행만 코드가 담당하는 역할 분리다.
_TRACKED_TOPIC_FIELDS = {
    "preferred_name", "favorite_foods", "food_dislikes", "usual_order_platform",
    "inconveniences", "health_notes", "household_size", "value_priority",
    "delivery_priority", "cooking_frequency", "meal_check",
}

# avoid_repeat_instruction에 화제를 사람이 읽을 수 있게 보여줄 때 쓰는
# 표시용 라벨 — 추적 자체는 위 필드명 그대로 하지만, 프롬프트에 필드명을
# 그대로 노출하면 부자연스럽다.
_TOPIC_FIELD_DISPLAY_LABEL = {
    "preferred_name": "이름/호칭",
    "favorite_foods": "좋아하는 음식",
    "food_dislikes": "못 먹거나 싫어하는 음식",
    "usual_order_platform": "장보는 곳",
    "inconveniences": "불편했던 점",
    "health_notes": "건강 관련 이야기",
    "household_size": "가구 인원",
    "value_priority": "가격 vs 품질 우선순위",
    "delivery_priority": "배송 속도 vs 배송비",
    "cooking_frequency": "요리 빈도",
    "meal_check": "식사 여부",
}


def _field_filled(merged: dict, field: str) -> bool:
    return merged.get(field) not in (None, [], "")


def _topic_still_pending(field: str, merged_profile: dict) -> bool:
    if field == "meal_check":
        # 연결된 profile 필드가 없는 안부성 질문(예: "식사는 하셨어요?")은
        # 필드 충족으로 자동 해제되지 않는다 — 한 번 물으면 온보딩이 끝날
        # 때까지 계속 "이미 물음" 상태로 남는다.
        return True
    return not _field_filled(merged_profile, field)


def _update_already_asked_topics(
    pending: list[str], asked_topic_field: Optional[str], reply_has_question: bool, merged_profile: dict
) -> list[str]:
    topics = set(pending)
    # reply_has_question(B-5 후처리 이후 실제로 질문이 남아있는지)로 한 번
    # 더 확인한다 — LLM이 asked_topic_field를 채웠어도 그 질문 문장이
    # B-5(물음표 개수 제한)로 잘려나갔다면 실제로는 안 물은 것이라 추적하면
    # 안 된다.
    if reply_has_question and asked_topic_field in _TRACKED_TOPIC_FIELDS:
        topics.add(asked_topic_field)
    topics = {t for t in topics if _topic_still_pending(t, merged_profile)}
    return sorted(topics)


# B-4: 가벼운 환각 방지 안전판. 완벽한 검증이 아니라 "최근 대화에 전혀
# 언급되지 않은 내용"만 걸러낸다 — 추출값이 실제 발화에 대응하는 최소한의
# 근거(2글자 이상 부분 문자열 중복)가 있는지만 확인한다.
def _filter_hallucinated_items(items: list[str], source_text: str) -> tuple[list[str], list[str]]:
    if not items:
        return items, []
    normalized_source = source_text.replace(" ", "")
    kept, dropped = [], []
    for item in items:
        normalized_item = item.replace(" ", "")
        if len(normalized_item) < 2:
            overlap = normalized_item in normalized_source
        else:
            overlap = any(
                normalized_item[i : i + 2] in normalized_source for i in range(len(normalized_item) - 1)
            )
        (kept if overlap else dropped).append(item)
    return kept, dropped


# B-5: 물음표 개수 제한 후처리 안전판. "물음표 최대 1개"(일반 턴)/"물음표
# 금지"(wrap-up·질문억제 턴) 지시를 프롬프트에 넣어도 모델이 확률적으로
# 안 따르는 사례가 실측에서 반복적으로 나왔다(예: 한 reply에 물음표가 2개
# 들어가는 경우, 생성 자체를 프롬프트만으로 막을 수는 없음) — 그래서
# B-1/B-2/B-4와 같은 패턴으로, reply를 다 받은 뒤 허용치를 넘는 물음표
# 문장을 코드로 제거한다. 초과분은 등장 순서상 앞쪽부터 제거하고 마지막
# 질문(들)을 남긴다 — 보통 마지막 질문이 진짜 이어가고 싶은 질문이고, 앞선
# 것들은 리액션 도중 곁가지로 붙은 경우가 많기 때문. 재생성(추가 LLM 호출)은
# 음성 에이전트의 레이턴시 민감도 때문에 쓰지 않는다. 문장이 하나만 남게
# 되면 더 지우지 않는다(무손실 우선).
#
# "물음표"만 세면 안 된다 — "어제는 뭐 드셨는지 궁금해요"처럼 물음표 없이도
# 사실상 질문인 문장이 실측에서 나왔다(reply 하나에 "궁금해요"형 암묵적
# 질문 + 물음표 있는 명시적 질문이 같이 들어가 총 2개의 질문 의도가 생김).
# 그래서 리터럴 "?" 외에 "궁금" 어간이 있는 문장도 질문으로 카운트한다.
_IMPLICIT_QUESTION_MARKERS = ("궁금",)


def _is_question_sentence(sentence: str) -> bool:
    return "?" in sentence or "？" in sentence or any(m in sentence for m in _IMPLICIT_QUESTION_MARKERS)


def _limit_questions(reply: str, max_questions: int) -> str:
    sentences = [s for s in re.split(r"(?<=[.!?？])\s+", reply.strip()) if s]
    if not sentences:
        return reply
    question_positions = [i for i, s in enumerate(sentences) if _is_question_sentence(s)]
    if len(question_positions) <= max_questions:
        return reply
    drop: set[int] = set()
    remaining_questions = list(question_positions)
    for idx in question_positions:
        if len(remaining_questions) <= max_questions:
            break
        if len(sentences) - len(drop) <= 1:
            break
        drop.add(idx)
        remaining_questions.remove(idx)
    if not drop:
        return reply
    return " ".join(s for i, s in enumerate(sentences) if i not in drop)


def _strip_trailing_question(reply: str) -> str:
    return _limit_questions(reply, max_questions=0)


def select_style_pattern(
    recent_patterns_used: list[str], is_thin_reply: bool = False
) -> tuple[str, str]:
    """같은 화법이 연속으로 반복되지 않도록, 최근 2~3턴에 안 쓴 패턴 중에서
    무작위로 하나 고른다. 전부 최근에 썼으면(4개뿐이라 3턴 안에 다 소진될
    수 있음) 전체 풀에서 다시 고른다."""
    if is_thin_reply:
        preferred = [k for k in ("guess", "balance") if k not in recent_patterns_used]
        if preferred:
            chosen_key = random.choice(preferred)
            return chosen_key, SMALLTALK_STYLE_PATTERNS[chosen_key]

    available = [k for k in SMALLTALK_STYLE_PATTERNS if k not in recent_patterns_used]
    if not available:
        available = list(SMALLTALK_STYLE_PATTERNS.keys())
    chosen_key = random.choice(available)
    return chosen_key, SMALLTALK_STYLE_PATTERNS[chosen_key]


def select_episode(recent_episodes_used: list[str]) -> tuple[str, str]:
    """select_style_pattern과 같은 원리 — 최근에 안 쓴 자기고백 소재를
    로테이션으로 골라서 "저도 그래요" 수준의 형식적 동조를 막는다."""
    available = [k for k in SMALLTALK_EPISODE_BANK if k not in recent_episodes_used]
    if not available:
        available = list(SMALLTALK_EPISODE_BANK.keys())
    chosen_key = random.choice(available)
    return chosen_key, SMALLTALK_EPISODE_BANK[chosen_key]


def is_thin_reply(user_input: str, newly_extracted_fields: dict) -> bool:
    """코드로 판별 가능한 짧은 맞장구인지 확인한다."""
    return len(user_input.strip()) <= 6 and not newly_extracted_fields


def _normalize_name_for_comparison(name: str) -> str:
    """"테스트유저"와 "테스트유저님"처럼 호칭 접미사·공백 차이만 있는 같은
    이름이 "새 이름"으로 오판되지 않게 정규화한다. LLM이 이미 아는 이름을
    reply에 자연스럽게 붙여 쓰면서(예: "~님") 구조화 출력에도 그 형태 그대로
    다시 추출하는 경우가 실측에서 나왔다 — 그러면 아래 비교가 매번 "새
    이름"으로 오판해서 name_greeting_pending이 계속 재점화되고, 그 사이엔
    화법 로테이션/화제 정체 감지(get_topic_stall_instruction)가 있는 최종
    분기 자체를 못 타는 부작용이 있었다."""
    normalized = name.strip()
    for suffix in ("님", "씨"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()
    return normalized


def _is_same_name(extracted: str, previous: str) -> bool:
    """호칭 접미사 차이(_normalize_name_for_comparison)뿐 아니라, 한쪽이
    다른 쪽의 부분 문자열인 경우(성을 생략하고 재추출·애칭 등)도 같은
    이름으로 본다. 실측에서 이름을 한 번만 알려준 세션인데도 몇 턴 지나서
    name_greeting_pending이 다시 True로 재점화되는 사례가 있었다 — 구조화
    출력은 매 턴 전체 필드를 다시 채워 보내는 특성상, LLM이 "김철수" 대신
    "철수"만 다시 추출하는 등 표현이 살짝 달라지는 것만으로 완전 일치
    비교가 "새 이름"으로 오판하는 게 원인으로 보인다."""
    a = _normalize_name_for_comparison(extracted)
    b = _normalize_name_for_comparison(previous)
    if not a or not b:
        return a == b
    return a == b or a in b or b in a


def _next_name_greeting_pending(
    *,
    was_pending: bool,
    greeting_consumed: bool,
    extracted_name: Optional[str],
    previous_name: Optional[str],
) -> bool:
    """이름 인지 힌트는 실제 사용된 다음 반드시 끄는 일회성 상태다.

    질문 억제 등 더 높은 우선순위 때문에 힌트를 쓰지 못했다면 유지하고,
    평소에는 이번 턴에 이름이 처음 생겼거나 실제로 바뀐 경우에만 켠다.
    LLM이 대화 이력의 기존 이름을 반복 추출하는 것은 새 이름으로 보지 않는다.
    """
    if greeting_consumed:
        return False
    if was_pending:
        return True
    if not extracted_name:
        return False
    return not _is_same_name(extracted_name, previous_name or "")


def check_episode_verbatim_copy(
    reply: str, episode_text: str, threshold: float = 0.6
) -> bool:
    """에피소드 원문의 과도한 재사용(연속 10자 또는 높은 유사도)을 찾는다."""
    normalized_reply = re.sub(r"\s+", " ", reply).strip()
    normalized_episode = re.sub(r"\s+", " ", episode_text).strip()
    if not normalized_reply or not normalized_episode:
        return False
    matcher = SequenceMatcher(None, normalized_reply, normalized_episode)
    longest_match = max((block.size for block in matcher.get_matching_blocks()), default=0)
    return longest_match >= 10 or matcher.ratio() > threshold


# 짧은 맞장구("그래", "응")에 대한 리액션이 전혀 다른 화제였던 직전 turn의
# 문구를 거의 그대로 재사용하는 현상이 실측(택배 얘기 때 리액션 문장을
# 나물/된장 얘기에도 토씨 하나 안 다르게 재사용)으로 확인됐다.
# check_episode_verbatim_copy와 같은 SequenceMatcher 기반 검증이지만, 대상이
# 고정 소재 텍스트가 아니라 "직전 봇 자신의 reply들"이라 별도 함수로 둔다.
# 음성 에이전트 레이턴시 때문에 재생성은 하지 않고(다른 B계열과 동일 원칙)
# 관측 가능한 경고 로그만 남긴다 — 실제 억제는 프롬프트 지시(화제 전환 힌트에
# "직전 리액션 재사용 금지" 추가)로 시도한다.
def check_reply_verbatim_reuse(reply: str, recent_replies: list[str], threshold: float = 0.6) -> bool:
    normalized_reply = re.sub(r"\s+", " ", reply).strip()
    if not normalized_reply:
        return False
    for prior in recent_replies:
        normalized_prior = re.sub(r"\s+", " ", prior).strip()
        if not normalized_prior:
            continue
        matcher = SequenceMatcher(None, normalized_reply, normalized_prior)
        longest_match = max((block.size for block in matcher.get_matching_blocks()), default=0)
        if longest_match >= 15 or matcher.ratio() > threshold:
            return True
    return False


def get_wrap_up_instruction(is_timeout: bool, is_field_complete: bool, is_thin_reply: bool = False) -> str:
    if is_timeout:
        base = _WRAP_UP_INSTRUCTION_TIMEOUT
    elif is_field_complete:
        base = _WRAP_UP_INSTRUCTION_NATURAL
    else:
        return ""
    return base + _WRAP_UP_THIN_REPLY_ADDENDUM if is_thin_reply else base


def check_completion_gate(
    llm_says_complete: bool,
    is_timeout: bool,
    is_order_handoff: bool = False,
    was_field_complete_before_turn: bool = False,
    health_followup_pending: bool = False,
) -> bool:
    """LLM이 onboarding_complete=true를 반환해도, 필수 필드가 안 채워졌으면
    이를 오버라이드하여 false로 되돌린다. 예외 둘:
    - is_timeout: 무한루프 방지를 위해 필드 미충족이어도 강제 종료.
    - is_order_handoff: 사용자가 명확한 주문 요청을 했을 때(SMALLTALK_ORDER_
      HANDOFF_RULE 해당)는 정보 수집보다 요청 처리가 우선이라는 원칙이 이미
      있고, 이 경로가 route_entry의 주문요청 우회와 함께 실측 테스트로
      검증된 흐름이라 필수 필드 게이트로 막으면 안 된다(스펙에 없던 파라미터를
      추가한 이유 — 필수 필드 게이트를 문자 그대로 적용하면 이 기존 동작이
      깨진다).

    필드 기반 완료는 collected_fields(이번 턴에 막 채워진 값 포함)가 아니라
    was_field_complete_before_turn(이번 턴 시작 "전" 이미 충족돼 있었는지)을
    본다 — 실측에서, 이번 턴 안에서 막 3/4 문턱을 넘긴 경우까지 즉시 완료를
    허용했더니 get_wrap_up_instruction이 이번 턴엔 아직 "필드 충족 전"으로
    보고 wrap-up 지시를 안 줘서, reply가 마무리 톤도 아니고 물음표도 안
    걸러진 채(B-5가 wrap-up 턴에만 적용됨) 갑자기 온보딩이 끝나버리는
    문제가 있었다. 그래서 "턴 시작 전부터 이미 충족돼 있었을 때"만 필드
    기반 완료를 허용한다 — 막 채워진 턴은 자연스럽게 한 턴 더 이어가고,
    바로 다음 턴은 profile_before가 이제 충족 상태라 wrap-up 지시가 정상
    발동해 깨끗하게 마무리된다.

    health_followup_pending=True면 필수 필드가 이미 다 채워졌어도(심지어
    4/4여도) 완료를 보류한다 — 건강 이슈(당뇨/고혈압 등)는 안전과 직결돼서,
    필수 필드 충족률과 무관하게 최소한의 후속 확인 없이 온보딩이 끝나면 안
    된다는 게 실측(당뇨 언급 직후 즉시 완료)으로 확인됐다. is_timeout/
    is_order_handoff는 이 경우에도 여전히 우선한다(무한루프 방지, 구매 요청
    처리 우선 원칙은 안전 확인보다 앞선 기존 예외라 그대로 둔다)."""
    if is_timeout or is_order_handoff:
        return True
    if not llm_says_complete:
        return False
    if health_followup_pending:
        return False
    return was_field_complete_before_turn


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


def _build_merged_profile(user_id: str, result: SmalltalkOutput) -> tuple[dict, bool]:
    """이번 턴 추출값을 기존 profile에 병합한 dict와 변경 여부만 계산하고,
    저장은 하지 않는다 — check_completion_gate가 "이번 턴까지 합치면 필수
    필드가 다 채워지는지"를 최종 onboarding_complete 결정 전에 먼저 봐야
    해서 계산과 저장을 분리했다."""
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
        merged["household_notes"] = db_client.merge_list_field(
            profile.get("household_notes"), p.household_notes
        )
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
        additions = [s.model_dump() for s in p.additional_signals]
        seen = {(str(s.get("label")), str(s.get("value"))) for s in existing if isinstance(s, dict)}
        unique_additions = []
        for signal in additions:
            key = (signal["label"], signal["value"])
            if key in seen:
                continue
            seen.add(key)
            unique_additions.append(signal)
        merged["additional_signals"] = list(existing) + unique_additions
        changed = True

    # 동일한 신호를 다시 추출한 경우 불필요한 DB write/computed_at 갱신을 막는다.
    return merged, merged != profile


def _save_profile_signals(
    user_id: str,
    result: SmalltalkOutput,
    merged: dict,
    changed: bool,
    mark_onboarded: bool,
) -> None:
    """_build_merged_profile 결과를 받아 실제 저장한다. 이번 턴에 온보딩이
    끝났다고 최종 판단되면(mark_onboarded=True, check_completion_gate로
    게이트된 값) 신호가 하나도 안 잡혀도 profile에 onboarded_at을 남겨야
    한다 — 이게 없으면 route_entry(src/graph/router.py)가 다음 턴에도 계속
    이 노드로 보내서 온보딩이 끝나지 않는다. 온보딩 진행 중인 턴은 뭔가
    실제로 추출됐을 때만 저장한다 — 매번 profile을 갱신하면 save_profile의
    computed_at도 매번 갱신돼서 RoutedSignal(general_context)의 timestamp
    의미가 흐려진다."""
    if mark_onboarded and not merged.get("onboarded_at"):
        merged["onboarded_at"] = datetime.now(timezone.utc).isoformat()
        changed = True

    if not changed:
        return

    db_client.save_profile(user_id, merged)
    agent_logger.log(
        f"[smalltalk_agent] profile 갱신 | preferred_name={result.preferred_name} "
        f"allergens+={result.new_allergens} "
        f"diet+={result.new_diet_restrictions} "
        f"profile+={result.profile.model_dump(exclude_defaults=True)}"
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
    recent_patterns_used = list(state.get("recent_patterns_used") or [])
    recent_episodes_used = list(state.get("recent_episodes_used") or [])
    consecutive_question_turns = int(state.get("consecutive_question_turns") or 0)
    name_greeting_pending = bool(state.get("name_greeting_pending", False))
    already_asked_topics_in = list(state.get("already_asked_topics") or [])
    stalled_turns_in = int(state.get("turns_without_required_progress") or 0)
    health_followup_remaining_in = int(state.get("health_followup_turns_remaining") or 0)
    recent_replies_in = list(state.get("recent_replies") or [])
    health_just_disclosed = detect_health_disclosure(user_input)
    health_followup_active = health_just_disclosed or health_followup_remaining_in > 0
    health_followup_instruction = ""
    topic_stall_target: Optional[str] = None
    chosen_pattern_key: Optional[str] = None
    chosen_episode_key: Optional[str] = None
    enforce_no_question = False  # wrap-up/질문억제 턴에서만 True — B-5 후처리 게이트
    name_greeting_consumed = False
    previous_preferred_name: Optional[str] = None

    if is_first_greeting:
        onboarding_started_at = datetime.now(timezone.utc).isoformat()
        elapsed_minutes = 0.0
        conversation_so_far = ""  # 첫 턴은 이전 대화가 없음(B-4 환각 검증용 소스 텍스트에도 사용)
        # 가입 시점에 이미 이름을 받아둔 유저는(runtime.py의
        # _seed_preferred_name_if_new) profile.preferred_name이 미리
        # 채워져 있다 — 그러면 온보딩 첫 턴에 이름을 또 묻지 않는다.
        # previous_preferred_name도 여기서 세팅해야, 이 턴에 LLM이 그
        # 이름을 다시 언급해도 "방금 새로 알게 된 이름"으로 오판해서
        # name_greeting_pending을 잘못 켜지 않는다.
        known_name_profile = db_client.get_profile(user_id) or {}
        profile_before = known_name_profile  # 화제 정체 카운터 계산에서 두 분기 공통으로 참조
        known_name = known_name_profile.get("preferred_name")
        previous_preferred_name = known_name
        # 힌트를 얹는 방식은 기존 "이름 물어보기" 지시(few-shot 예시 포함)가
        # 더 강해서 실측에서 매번 졌다 — wrap-up/질문억제와 같은 교훈으로,
        # 경쟁하는 지시 자체를 통째로 교체한다(smalltalk_prompt.py 참고).
        greeting_flow_instruction = (
            SMALLTALK_GREETING_FLOW_KNOWN_NAME.format(name=known_name)
            if known_name
            else SMALLTALK_GREETING_FLOW_UNKNOWN_NAME
        )
        agent_logger.log(
            f"[smalltalk_agent] 진입 | user_id={user_id} (온보딩 1턴째, 인사, known_name={known_name!r})"
        )
        prompt = SMALLTALK_GREETING_PROMPT.format(
            persona=SMALLTALK_PERSONA,
            profile_field_guide=SMALLTALK_PROFILE_FIELD_GUIDE,
            order_handoff_rule=SMALLTALK_ORDER_HANDOFF_RULE,
            safety_field_note=SMALLTALK_SAFETY_FIELD_NOTE,
            greeting_flow_instruction=greeting_flow_instruction,
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
        profile_before = db_client.get_profile(user_id) or {}
        previous_preferred_name = profile_before.get("preferred_name")
        collected_so_far = format_smalltalk_profile(profile_before)
        thin_reply = is_thin_reply(user_input, {})
        frustration_detected = detect_frustration(user_input)
        wrap_up_instruction = get_wrap_up_instruction(
            is_timeout=past_cap,
            # health_followup_active면 필수 필드가 다 채워졌어도 이번 턴은
            # 마무리 턴으로 취급하지 않는다 — 건강 화제를 더 확인해야 한다
            # (아래 health_followup_instruction 분기). is_timeout은 예외로
            # 그대로 둔다(무한루프 방지가 안전 확인보다 우선).
            is_field_complete=_required_fields_filled(profile_before) and not health_followup_active,
            is_thin_reply=thin_reply,
        )
        suppress_question = (
            consecutive_question_turns >= _MAX_CONSECUTIVE_QUESTION_TURNS
            or stalled_turns_in >= _QUESTION_SUPPRESSION_STALL_SAFETY_NET
        )
        name_greeting_hint = (
            SMALLTALK_NAME_GREETING_HINT.format(name=profile_before.get("preferred_name") or "어르신")
            if name_greeting_pending
            else ""
        )

        # 조건부 조각 우선순위: wrap-up/질문억제는 질문 생성 조각을 제거하고,
        # 이름 인지 턴은 화법·에피소드·화제전환과 배타적이다. 얇은 답변 전환은
        # 위 세 조건이 없을 때만 일반 화법/에피소드와 함께 활성화된다.
        topic_pivot_hint = ""
        topic_stall_instruction = ""
        avoid_repeat_instruction = ""
        episode_hint = ""
        if wrap_up_instruction:
            # 화법 예시가 질문으로 끝나는 few-shot이라, "이 지시가 우선합니다"
            # 같은 override 문구만으로는 실제로 안 이겨서(실측 확인됨) —
            # 마무리 턴엔 아예 화법 패턴을 안 보여줘서 경쟁 신호 자체를 없앤다.
            chosen_pattern_key = None
            style_pattern = "(이번 턴은 마무리 턴이라 화법 예시를 생략합니다 — 아래 마무리 지시를 그대로 따르세요.)"
            name_greeting_hint = ""
        elif health_followup_active:
            # 안전(건강)이 다른 화제 정체/질문 억제/이름 안부보다 우선한다 —
            # 이 화제만큼은 다른 화제로 새지 않고, 질문 연속 억제 규칙도
            # 이번 턴만큼은 적용하지 않는다(아래 enforce_no_question 계산 참고).
            chosen_pattern_key = None
            style_pattern = "(이번 턴은 건강 이슈를 더 확인해야 해서 화법 예시를 생략합니다 — 아래 건강 확인 지시를 그대로 따르세요.)"
            name_greeting_hint = ""
            health_followup_instruction = get_health_followup_instruction(health_just_disclosed)
            agent_logger.log(
                f"[smalltalk_agent] 건강 이슈 후속 확인 강제 | "
                f"just_disclosed={health_just_disclosed} remaining_in={health_followup_remaining_in}"
            )
        elif suppress_question:
            # 최근 연속으로 질문 턴이 이어졌을 때도 같은 원리로, 화법 예시를
            # 억제 문구로 완전히 교체한다(단순히 "질문하지 마세요"를 덧붙이는
            # 것만으론 few-shot을 못 이긴다는 게 wrap-up에서 이미 확인됨).
            chosen_pattern_key = None
            style_pattern = _QUESTION_SUPPRESSION_STYLE_OVERRIDE
            name_greeting_hint = ""
            agent_logger.log(
                f"[smalltalk_agent] 질문 연속 {consecutive_question_turns}턴 — 이번 턴 질문 강제 생략"
            )
        elif name_greeting_hint:
            chosen_pattern_key = None
            style_pattern = ""
            name_greeting_consumed = True
        else:
            chosen_pattern_key, style_pattern = select_style_pattern(
                recent_patterns_used, is_thin_reply=thin_reply
            )
            chosen_episode_key, episode_hint = select_episode(recent_episodes_used)
            if thin_reply:
                topic_pivot_hint = SMALLTALK_TOPIC_PIVOT_HINT
            # topic_stall_instruction과 avoid_repeat_instruction을 동시에
            # 켜면 "이 규칙이 다른 모든 지시보다 우선합니다"라고 주장하는
            # 블록이 한 턴에 두 개가 되는데, 실측에서 이 경우 모델이 둘 다
            # 무시하고 원래 화제를 이어가는 현상이 확인됐다(두 "최우선"이
            # 서로 신호를 희석시키는 것으로 보임) — 그래서 한 턴엔 하나만
            # 켠다. 사용자가 명시적으로 항의했으면("아까 말했잖아") 그게
            # 가장 급하니 최우선, 아니면 화제 정체(필수 필드 진행 없음)가
            # 특정 필드로의 전환까지 지정해주므로 더 구체적인 쪽을 우선한다
            # — 화제 정체로 전환하면 "다시 묻지 마세요"까지 자연히 만족된다
            # (전환 대상 자체가 이미 물은 화제가 아니므로).
            if frustration_detected:
                avoid_repeat_instruction = get_avoid_repeat_instruction(already_asked_topics_in, True)
                agent_logger.log(
                    f"[smalltalk_agent] 화제 반복 방지 지시 주입(항의 감지) | pending={already_asked_topics_in}"
                )
            elif stalled_turns_in >= _TOPIC_STALL_TURN_THRESHOLD:
                topic_stall_target = _topic_stall_target_field(profile_before, stalled_turns_in)
                topic_stall_instruction = get_topic_stall_instruction(profile_before, stalled_turns_in)
                if topic_stall_instruction:
                    agent_logger.log(
                        f"[smalltalk_agent] 화제 정체 {stalled_turns_in}턴 연속 — 필수 필드로 강제 전환"
                    )
                else:
                    # 채울 필수 필드가 이미 없으면(get_topic_stall_instruction이
                    # 빈 문자열 반환) 정체 전환 지시가 무의미하므로, 그 다음
                    # 우선순위인 화제 반복 방지로 대체한다.
                    avoid_repeat_instruction = get_avoid_repeat_instruction(already_asked_topics_in, False)
                    if avoid_repeat_instruction:
                        agent_logger.log(
                            f"[smalltalk_agent] 화제 반복 방지 지시 주입 | pending={already_asked_topics_in}"
                        )
            else:
                # B-3(already_asked_topics)를 "다시 묻지 마세요"라고 대화
                # 중간 문단에서만 언급했더니 실측에서 무시되고 같은 질문이
                # 반복됐다 — wrap-up/질문억제와 같은 후반부 강한 지시로 승격한다.
                avoid_repeat_instruction = get_avoid_repeat_instruction(already_asked_topics_in, False)
                if avoid_repeat_instruction:
                    agent_logger.log(
                        f"[smalltalk_agent] 화제 반복 방지 지시 주입 | pending={already_asked_topics_in}"
                    )
        # health_followup_active는 질문 연속 억제보다 우선한다 — 안전 확인
        # 질문은 "질문이 너무 잦았다"는 UX 이유로 막으면 안 된다.
        enforce_no_question = bool(wrap_up_instruction) or (suppress_question and not health_followup_active)
        # wrap-up/건강확인이 이미 질문 여부를 스스로 규정하므로, 그 턴엔 중복으로 넣지 않는다.
        question_suppression_instruction = (
            _QUESTION_SUPPRESSION_INSTRUCTION
            if (suppress_question and not wrap_up_instruction and not health_followup_active)
            else ""
        )
        already_asked_display = ", ".join(
            _TOPIC_FIELD_DISPLAY_LABEL.get(t, t) for t in already_asked_topics_in
        ) or "(없음)"
        prompt = SMALLTALK_CHAT_PROMPT.format(
            persona=SMALLTALK_PERSONA,
            profile_field_guide=SMALLTALK_PROFILE_FIELD_GUIDE,
            topic_guide=SMALLTALK_TOPIC_GUIDE,
            order_handoff_rule=SMALLTALK_ORDER_HANDOFF_RULE,
            safety_field_note=SMALLTALK_SAFETY_FIELD_NOTE,
            style_pattern=style_pattern,
            episode_hint=episode_hint,
            topic_pivot_hint=topic_pivot_hint,
            name_greeting_hint=name_greeting_hint,
            already_asked_topics=already_asked_display,
            collected_so_far=collected_so_far,
            wrap_up_instruction=wrap_up_instruction,
            health_followup_instruction=health_followup_instruction,
            question_suppression_instruction=question_suppression_instruction,
            topic_stall_instruction=topic_stall_instruction,
            avoid_repeat_instruction=avoid_repeat_instruction,
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

    # B-5: 물음표 개수 제한 후처리 — "물음표 최대 1개"(일반/인사 턴) 또는
    # "물음표 금지"(wrap-up/질문억제 턴) 지시를 프롬프트로 줬는데도 모델이
    # 확률적으로 안 따른 경우(예: 한 reply에 물음표 2개)를 코드로 결정론적
    # 으로 막는다. GREETING_PROMPT에도 같은 "최대 1개" 규칙이 있으므로
    # 인사 턴 포함 모든 턴에 적용한다.
    max_questions = 0 if enforce_no_question else 1
    limited_reply = _limit_questions(result.reply, max_questions)
    if limited_reply != result.reply:
        agent_logger.log(
            f"[smalltalk_agent] 물음표 초과({max_questions}개 제한)로 문장 제거 | "
            f"before={result.reply!r} after={limited_reply!r}"
        )
        result.reply = limited_reply

    if chosen_episode_key and check_episode_verbatim_copy(
        result.reply, SMALLTALK_EPISODE_BANK[chosen_episode_key]
    ):
        # 음성 응답 레이턴시 때문에 재생성하지 않고 관측 가능한 경고로 남긴다.
        agent_logger.log(
            "[smalltalk_agent] episode_hint 원문 과다 재사용 감지 | "
            f"episode={chosen_episode_key} reply={result.reply!r}"
        )

    if check_reply_verbatim_reuse(result.reply, recent_replies_in):
        # 짧은 맞장구 턴에서 전혀 다른 화제였던 직전 reply 문구를 거의
        # 그대로 재사용하는 현상을 감지한다 — 재생성은 안 하고 경고만 남긴다.
        agent_logger.log(
            "[smalltalk_agent] 직전 reply 원문 과다 재사용 감지 | "
            f"reply={result.reply!r} recent={recent_replies_in!r}"
        )

    # B-1: 안전 필드 교차검증 — food_dislikes에 의학적 키워드가 섞여 있으면
    # new_diet_restrictions로 재분류(LLM 판단만 믿지 않음).
    kept_dislikes, promoted_to_restrictions = _reclassify_medical_food_dislikes(result.profile.food_dislikes)
    if promoted_to_restrictions:
        agent_logger.log(
            f"[smalltalk_agent] 안전 필드 재분류 | food_dislikes -> new_diet_restrictions: "
            f"{promoted_to_restrictions}"
        )
        result.profile.food_dislikes = kept_dislikes
        result.new_diet_restrictions = result.new_diet_restrictions + promoted_to_restrictions

    # B-2: 방향성 필드 교차검증 — 사용자 발화 키워드와 반대로 뽑혔으면 정정.
    corrected_fields = _cross_check_directional_fields(result.profile, user_input)
    if corrected_fields:
        agent_logger.log(
            f"[smalltalk_agent] 방향성 필드 교차검증으로 정정됨: {corrected_fields} "
            f"(user_input={user_input!r})"
        )

    # B-4: 가벼운 환각 방지 — 최근 대화에 전혀 없던 내용만 걸러낸다.
    hallucination_source = conversation_so_far + user_input
    for list_field in ("food_dislikes", "favorite_foods", "health_notes", "inconveniences", "household_notes"):
        original = getattr(result.profile, list_field)
        kept, dropped = _filter_hallucinated_items(original, hallucination_source)
        if dropped:
            agent_logger.log(f"[smalltalk_agent] 환각 의심으로 제외됨 | {list_field}: {dropped}")
            setattr(result.profile, list_field, kept)
    for top_field in ("new_allergens", "new_diet_restrictions"):
        original = getattr(result, top_field)
        kept, dropped = _filter_hallucinated_items(original, hallucination_source)
        if dropped:
            agent_logger.log(f"[smalltalk_agent] 환각 의심으로 제외됨 | {top_field}: {dropped}")
            setattr(result, top_field, kept)

    merged_profile, changed = _build_merged_profile(user_id, result)

    # 화제 정체 강제 개입 — topic_stall_instruction(소프트 지시)이 이미
    # _TOPIC_STALL_FORCE_AFTER_IGNORED_TURNS턴 넘게 무시됐는데도 이번 턴도
    # 지정된 필드를 안 물었으면(그리고 그 필드가 이번 턴 추출로도 안
    # 채워졌으면), reply를 직접 고쳐서 그 질문을 강제로 붙인다. B-5와 같은
    # "지시만으론 안 되면 코드로" 원칙이지만, 여긴 지시 위반이 여러 턴
    # 반복될 때만 쓰는 마지막 수단이라 다른 B계열보다 개입 폭이 크다.
    force_pivot_fired = False
    if (
        topic_stall_target
        and result.asked_topic_field != topic_stall_target
        and not _field_filled(merged_profile, topic_stall_target)
        and stalled_turns_in >= _TOPIC_STALL_TURN_THRESHOLD + _TOPIC_STALL_FORCE_AFTER_IGNORED_TURNS
    ):
        forced_reply = force_topic_pivot_reply(result.reply, topic_stall_target)
        agent_logger.log(
            f"[smalltalk_agent] 화제 정체 지시 {stalled_turns_in}턴 연속 무시 — 강제 개입 | "
            f"target={topic_stall_target} before={result.reply!r} after={forced_reply!r}"
        )
        result.reply = forced_reply
        result.asked_topic_field = topic_stall_target
        result.onboarding_complete = False
        force_pivot_fired = True

    # 브랜치 무관 화제 반복 감지 — avoid_repeat_instruction은 else(정상)
    # 브랜치에서, 그것도 화제 정체가 아닐 때만 계산된다(topic_stall_
    # instruction과 같은 턴에 "최우선" 블록 두 개를 넣으면 둘 다 무시되는
    # dilution 문제 때문에 배타적으로 유지). 그런데 화제 정체(다른 화제로
    # 전환하라는 지시)와 "이 화제는 이미 물었다"는 서로 다른 문제라, 정체
    # 턴엔 후자를 감시할 지시 슬롯이 아예 없다 — 위 topic_stall_target이
    # 커버하는 4개 필수 필드 밖의 화제(favorite_foods/usual_order_platform/
    # inconveniences/health_notes/meal_check/preferred_name)가 반복돼도
    # 어떤 브랜치가 그 턴을 처리했는지와 무관하게 걸러지도록, 최종 reply
    # 결과만 보고 결정론적으로 재작성한다.
    if not force_pivot_fired and _is_cross_branch_repeat(
        reply_has_question=_is_question_sentence(result.reply),
        asked_topic_field=result.asked_topic_field,
        already_asked_topics=already_asked_topics_in,
        health_followup_active=health_followup_active,
        topic_stall_target=topic_stall_target,
    ):
        rewritten_reply, new_target = force_repeat_avoidance_reply(
            result.reply, merged_profile, stalled_turns_in
        )
        agent_logger.log(
            f"[smalltalk_agent] 브랜치 무관 화제 반복 감지 — 강제 개입 | "
            f"field={result.asked_topic_field} before={result.reply!r} after={rewritten_reply!r}"
        )
        result.reply = rewritten_reply
        result.asked_topic_field = new_target

    is_order_handoff = _looks_like_explicit_order_request(user_input)
    onboarding_complete = check_completion_gate(
        llm_says_complete=result.onboarding_complete,
        is_timeout=past_cap,
        is_order_handoff=is_order_handoff,
        was_field_complete_before_turn=_required_fields_filled(profile_before),
        health_followup_pending=health_followup_active,
    )
    if result.onboarding_complete and not onboarding_complete:
        reason = "건강 이슈 후속 확인 미완료" if health_followup_active else "필수 필드 미충족"
        agent_logger.log(
            f"[smalltalk_agent] LLM은 종료(onboarding_complete=true)를 원했지만 "
            f"{reason} — 게이트가 override, 대화 계속"
        )
    if past_cap and not onboarding_complete:
        # 이론상 check_completion_gate가 is_timeout이면 항상 True를 반환하므로
        # 도달하지 않아야 하는 분기지만, 안전망으로 로그만 남기고 강제 종료.
        agent_logger.log(f"[smalltalk_agent] 온보딩 제한시간({_MAX_ONBOARDING_MINUTES}분) 도달 — 강제 종료")
        onboarding_complete = True

    _save_profile_signals(user_id, result, merged_profile, changed, mark_onboarded=onboarding_complete)
    reply_has_question = _is_question_sentence(result.reply)
    agent_logger.log(
        f"[smalltalk_agent] 응답: {result.reply} "
        f"(onboarding_complete={onboarding_complete}, style_pattern={chosen_pattern_key}, "
        f"episode={chosen_episode_key}, has_question={reply_has_question})"
    )

    if onboarding_complete:
        new_recent_patterns: list[str] = []
        new_recent_episodes: list[str] = []
        new_consecutive_question_turns = 0
        new_name_greeting_pending = False
        new_already_asked_topics: list[str] = []
        new_turns_without_required_progress = 0
        new_health_followup_remaining = 0
        new_recent_replies: list[str] = []
    else:
        new_recent_patterns = (
            (recent_patterns_used + [chosen_pattern_key])[-3:] if chosen_pattern_key else recent_patterns_used
        )
        new_recent_episodes = (
            (recent_episodes_used + [chosen_episode_key])[-3:] if chosen_episode_key else recent_episodes_used
        )
        # 물음표 유무가 아니라 "정보요청형" 질문인지로 카운트한다 —
        # meal_check(안부성)와 null(리액션에 얹힌 감탄형)은 정보 수집이
        # 목적이 아니므로 취조 피로도에 안 넣는다(모듈 상단 _MAX_
        # CONSECUTIVE_QUESTION_TURNS 주석 참고).
        is_information_seeking_question = (
            reply_has_question
            and result.asked_topic_field in _TRACKED_TOPIC_FIELDS
            and result.asked_topic_field != "meal_check"
        )
        new_consecutive_question_turns = (
            consecutive_question_turns + 1 if is_information_seeking_question else 0
        )
        # "방금 이름을 막 알게 됐는지"를 LLM의 대화 이력 추론에 맡기지 않고,
        # 이번 턴에 preferred_name이 실제로 채워졌는지로 결정적으로 판단한다
        # (모듈 docstring 참고) — 다음 턴 CHAT_PROMPT에 안부 힌트를 주입할지를 정한다.
        new_name_greeting_pending = _next_name_greeting_pending(
            was_pending=name_greeting_pending,
            greeting_consumed=name_greeting_consumed,
            extracted_name=result.preferred_name,
            previous_name=previous_preferred_name,
        )
        # B-3: 이번 턴 LLM이 보고한 asked_topic_field를 추가하고,
        # merged_profile에서 이미 채워진 화제는 뺀다.
        new_already_asked_topics = _update_already_asked_topics(
            already_asked_topics_in, result.asked_topic_field, reply_has_question, merged_profile
        )
        # 화제 정체 카운터: 이번 턴에 필수 필드가 새로 하나라도 채워졌으면
        # 리셋, 아니면 +1(get_topic_stall_instruction이 임계치에서 강제 전환).
        before_required_count = _required_fields_filled_count(profile_before)
        after_required_count = _required_fields_filled_count(merged_profile)
        new_turns_without_required_progress = (
            0 if after_required_count > before_required_count else stalled_turns_in + 1
        )
        # 건강 화제 후속 카운터: 방금 새로 감지됐으면 최소 유지 턴수로 리셋,
        # 진행 중이었으면 1 감소, 아니면 0 유지.
        new_health_followup_remaining = (
            _HEALTH_FOLLOWUP_EXTRA_TURNS if health_just_disclosed
            else max(0, health_followup_remaining_in - 1)
        )
        new_recent_replies = (recent_replies_in + [result.reply])[-2:]

    return {
        "explanation": result.reply,
        "immediate_response": result.reply,
        "pending_action": None,
        "onboarding_started_at": None if onboarding_complete else onboarding_started_at,
        "recent_patterns_used": new_recent_patterns,
        "recent_episodes_used": new_recent_episodes,
        "consecutive_question_turns": new_consecutive_question_turns,
        "name_greeting_pending": new_name_greeting_pending,
        "already_asked_topics": new_already_asked_topics,
        "turns_without_required_progress": new_turns_without_required_progress,
        "health_followup_turns_remaining": new_health_followup_remaining,
        "recent_replies": new_recent_replies,
        "stage": "idle",
        "last_agent": "smalltalk_agent",
        "error": None,
    }
