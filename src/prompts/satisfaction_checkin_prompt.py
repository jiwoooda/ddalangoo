"""
만족도 체크인 프롬프트 — src/agents/satisfaction_checkin.py가 쓴다.

smalltalk_agent(온보딩 딸랑구 캐릭터)와 같은 SMALLTALK_PERSONA를 그대로
재사용한다(호출부에서 import) — 비슷한 페르소나 텍스트를 새로 만들지 않고,
톤/캐릭터가 확실히 같아지도록 한다.
"""

SATISFACTION_ASK_PROMPT = """\
{persona}

사용자가 지금 딱히 급한 용건이 없어 보입니다. 이럴 때 예전에 산 상품에 대해
가볍게 안부를 묻듯 물어보세요 — 설문조사처럼 딱딱하게 묻지 말고, 정말
궁금해서 묻는 것처럼 자연스럽게.

# 물어볼 상품
{product_name} (구매일: {purchased_at})

# 지침
- 1~2문장, 짧고 부담 없이. 물음표는 최대 1개.
- "만족하셨나요?" 같은 설문형 문장 대신, "그때 산 {product_name}은
  어떠셨어요?"처럼 자연스러운 안부 톤으로 물으세요.
- satisfaction/note는 이 턴엔 채우지 마세요 — 아직 답을 못 들었으므로 항상
  null입니다.
"""

SATISFACTION_CAPTURE_PROMPT = """\
{persona}

방금 사용자에게 "{product_name}"에 대한 만족도를 물었고, 아래는 그 답변입니다.

# 사용자 답변
{user_text}

# 지침
1. reply: 답변에 대한 짧고 진심 어린 리액션 한 문장. 새로운 질문을 던지거나
   화제를 더 이어가려 하지 마세요 — 리액션만으로 자연스럽게 끝내세요.
2. satisfaction: 답변의 뉘앙스를 positive/neutral/negative 중 하나로
   분류하세요. 답변이 만족도와 무관하거나(예: 딴 얘기로 넘어감) 판단하기
   애매하면 null로 두세요 — 추측해서 억지로 채우지 마세요.
3. note: 구체적인 코멘트가 있으면(예: "너무 셔서 별로였어요") 짧게 요약해서
   적으세요. 없으면 null.
"""
