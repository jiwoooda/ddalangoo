"""
프로필 이어 묻기(profile top-up) 프롬프트 — src/agents/profile_topup.py가 쓴다.

smalltalk_agent(온보딩)와 같은 SMALLTALK_PERSONA + SMALLTALK_PROFILE_FIELD_GUIDE를
그대로 재사용한다(호출부에서 import) — 온보딩 때 안 채워진 프로필 필드를 나중에
이어서 채우는 것뿐이라, 필드 정의가 온보딩 때와 갈라지면 안 된다.
"""

PROFILE_TOPUP_ASK_PROMPT = """\
{persona}

사용자가 지금 딱히 급한 용건이 없어 보입니다. 이럴 때 아직 못 여쭤본 부분을
가볍게 물어보면 좋습니다 — 설문조사처럼 딱딱하게 묻지 말고, 자연스러운
대화처럼.

# 프로필 필드 설명
{profile_field_guide}

# 이번에 물어볼 필드
{field}

# 이미 알고 있는 정보 (참고용 — 다시 묻지 마세요)
{known_profile}

# 지침
- 1~2문장, 짧고 부담 없이. 물음표는 최대 1개.
- 위 필드를 그대로 설문 문항처럼 묻지 말고, 자연스러운 질문으로 바꿔서
  물으세요(예: usual_order_platform → "장 보실 때 주로 어디서 주문하세요?").
- profile 필드는 이 턴엔 채우지 마세요(아직 답을 못 들었으므로 항상 비워둠).
"""

PROFILE_TOPUP_CAPTURE_PROMPT = """\
{persona}

방금 사용자에게 아래 내용을 물었고, 이어서 답변이 왔습니다.

# 방금 물은 것
{asked_message}

# 사용자 답변
{user_text}

# 프로필 필드 설명
{profile_field_guide}

# 지침
1. reply: 답변에 대한 짧고 진심 어린 리액션 한 문장. 새로운 질문을 던지거나
   화제를 더 이어가려 하지 마세요 — 리액션만으로 자연스럽게 끝내세요.
2. profile: 답변에서 실제로 드러난 값만 채우세요. 방향이 있는 필드
   (value_priority/delivery_priority/cooking_frequency)는 조금이라도
   헷갈리면 비워두세요. 실제로 나온 얘기가 아니면 절대 지어내지 마세요.
"""
