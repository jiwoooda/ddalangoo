"""
Context Agent 프롬프트 — 초안. 세부 문구는 추후 별도 조정 예정.

CONTEXT_CLASSIFICATION_PROMPT: General Context(장기 프로필 요약) + User DB
(키워드 관련 구매이력 raw, satisfaction/memo 포함) + 세션 대화를 받아
routed_signals(RoutedSignal 리스트)로 분류한다. 각 신호는 value/source/
evidence/decision_role만 LLM이 채우고, signal_id/timestamp는 코드가
source 기준으로 채운다 (LLM이 시각을 추측하지 않는다).

safety_constraints(알레르기 등)는 이 프롬프트의 출력 대상이 아니다 —
프로필에서 코드로 직접 채워 넣는다 (LLM이 안전 판단에 관여하지 않도록).
새로 감지되는 안전 정보는 SAFETY_SYNC_PROMPT가 별도로, 이 분류보다
먼저 동기적으로 처리한다 (build_preference_context 참고).

smalltalk_agent가 수집한 구조화 프로필(food_dislikes/value_priority/
delivery_priority/household_size/household_notes/cooking_frequency/
additional_signals, src.state.smalltalk_schema.SmalltalkProfileSchema)은
"장기 프로필 요약"과 별도 섹션으로 보여준다 — 일반 profile 필드와 섞이면
안전정보(allergens 등 tier1)와 구분이 흐려지기 쉬워서다. food_dislikes는
안전 배제(tier1)가 아니라 명시적 제외(tier2)에 가깝다는 점을 LLM이
구분하도록 아래 explicit_exclusion 기준을 그대로 적용한다.
"""

SAFETY_SYNC_PROMPT = """\
아래는 쇼핑 어시스턴트 세션의 최근 대화입니다. 사용자가 이번 세션에서
"처음으로" 언급한 알레르기/식이제약 정보가 있는지 확인하세요.

이미 알고 있던 정보를 재언급한 것인지, 새로 언급한 것인지는 구분할 수
없으니(이 프롬프트는 그 정보를 모릅니다), 대화에 알레르기/식이제약으로
해석될 만한 내용이 있으면 전부 추출하세요 — 중복 저장은 이후 병합
단계에서 코드가 처리합니다.

추출 대상 아닌 것: "질 좋은 거 선호", "1인분만" 같은 일반 선호. 이건
알레르기/식이제약이 아닙니다 — 새로 만들지 마세요.

정보가 없으면 두 리스트 모두 빈 리스트로 반환하세요.

# 최근 대화
{session_text}
"""

CONTEXT_CLASSIFICATION_PROMPT = """\
당신은 쇼핑 어시스턴트의 Context 분류기입니다. 아래 정보를 보고 이번 요청에
반영할 신호를 routed_signals 리스트로 뽑으세요. 신호 하나마다 value(내용) /
source(어느 입력에서 왔는지) / evidence(근거가 된 원문/데이터) /
decision_role(용도) 네 가지를 채우세요.

[다중 라우팅]
하나의 원시 정보가 여러 decision_role에 동시에 해당할 수 있습니다.
이 경우 routed_signals에 각각 별도 신호로 나눠 담으세요 (하나의 신호가
두 role을 동시에 갖지 않습니다).
예: 유당불내증 → retrieval("락토프리 우유") + explicit_exclusion
    ("우유") 두 개로 분리. 검색 keyword로 좁혀도, 검색이 완벽하지
    않을 수 있으니 필터 단계에서 이중 안전장치로 작동합니다.

[개수 제한]
retrieval 신호는 최대 5개, soft_preference 신호는 최대 5개까지만
뽑으세요. 그 이상 넘어가면 정말 중요한 것 위주로 추리세요
(예: 이번 세션 발화 > 장기 프로필, 명확한 것 > 애매한 것 순으로 우선).
explicit_exclusion과 안전 관련 신호는 이 제한에 포함되지 않습니다.

[decision_role별 기준]
- retrieval: 검색 결과가 실제로 좁혀져야 하는 속성. 아래 두 소스 모두에서
  뽑되, 반드시 "실제 검색 키워드로 쓸 수 있는 구체적인 말"로 바꿔서
  value에 넣으세요.
  (1) 이번 세션 발화에서 명확히 "원한다"고 표현한 속성 — 그대로 키워드화.
  (2) 장기 프로필의 추상적 제약/선호 — 아래처럼 구체적인 검색 키워드로
      번역해서 반영하세요. 프로필 항목을 그대로 옮기면 안 됩니다.
        "유당불내증" → "락토프리 우유"
        "저당 선호" 성향 프로필 → "저당"
      세션 발화도 마찬가지로 번역이 필요할 수 있습니다:
        "요즘 다이어트 중이라..." → "저당"

  [retrieval 판단 기준] 이 속성이 빠지면 검색 결과가 아예 다른 카테고리/
  품목이 되는가? 그리고 이 속성이 상품명이나 카테고리 텍스트에 통상
  그대로 나타나는가? 둘 다 "예"일 때만 retrieval로 분류하세요.

  좋은 예: "저당" (상품명에 "저당 요거트"처럼 통상 나타남)
  좋은 예: "락토프리" (상품명에 통상 나타남)
  나쁜 예: "프리미엄" — 가격대 선호는 상품명에 일관되게 나타나지 않음.
           soft_preference로 분류하세요.
  나쁜 예: "샛별배송" — 배송 방식은 상품명이 아니라 별도 파라미터
           영역이라, 검색 keyword로 넣으면 결과가 왜곡될 수 있습니다.
           soft_preference로 분류하세요 (실제 배송필터 지원 여부는
           검색 단계에서 별도 판단).
  나쁜 예: "1인분만" — 이건 상품 규격 텍스트에서 추론이 필요한 성격이라
           soft_preference입니다. retrieval로 넣으면 오히려 적합한
           대용량-소분 가능 상품이 검색에서 배제될 수 있습니다.

- explicit_exclusion: 명확히 배제해야 할 대상. value에는 반드시 상품명/
  브랜드에 실제로 나타날 법한 단순 키워드만 넣으세요. 문장이나 이유를
  그대로 옮기지 마세요.

  [explicit_exclusion 예시]
  상황: 사용자가 "죽향 딸기는 예전에 별로였음"이라고 했거나, 아래 구매이력에
  "죽향 딸기 1kg"의 만족도가 낮게 기록되어 있음.
    좋은 예: value="죽향"  (브랜드명만, 상품명에 실제로 나타나는 단어)
    좋은 예: value="딸기"  (품목명만)
    나쁜 예: value="예전에 별로였던 죽향 딸기"  (문장을 그대로 옮김 — 매칭 안 됨)
    나쁜 예: value="가격 후려친 딸기는 별로"  (이유/뉘앙스까지 포함 — 매칭 불가능)
    나쁜 예: value="그 브랜드는 별로였음"  (브랜드명이 아니라 지시어를 그대로 옮김)
  evidence에는 어떤 발화/구매이력 레코드가 근거인지 원문을 남기세요.

- soft_preference: 배제 근거로 쓰기엔 확신이 없는 뉘앙스性 선호/비선호,
  또는 검색 키워드로 쓰기엔 상품명에 나타나지 않는 속성. 배제에 쓰이지
  않고 랭킹 가중치로만 사용됩니다.

  [soft_preference로 분류하는 경우]
  - "질 좋은 거 선호" (상품명으로 판단 불가, 추론 필요)
  - "1인분만" (상품 규격 텍스트에서 추론 필요)
  - 반복 구매 패턴이 혼재된 경우 (예: 가끔 프리미엄, 가끔 최저가)
  - retrieval 기준(위)을 통과 못 하는 명확한 요구 (예: "샛별배송",
    "프리미엄")

  [soft_preference로 분류하지 않는 경우]
  - 알레르기/식이제약 → 이미 safety_constraints로 별도 처리되므로
    여기 포함하지 마세요.
  - 상품명/브랜드에 실제 나타날 단순 키워드로 표현 가능한 명확한
    배제 신호 → explicit_exclusion으로 보내세요.

[잡담에서 수집된 정보 섹션 — 반드시 분류할 것]
아래 "잡담(smalltalk_agent)에서 수집된 정보" 섹션에 "없음"이 아닌 내용이
있으면, 절대 무시하지 말고 각 항목을 반드시 routed_signal로 분류하세요:
- food_dislikes: explicit_exclusion 우선 고려 (알레르기처럼 확정적인 배제는
  아니지만, 상품명/재료명에 나타날 단순 키워드로 바꿀 수 있으면
  explicit_exclusion — 위 explicit_exclusion 기준을 그대로 적용).
- health_notes: food_dislikes와 동일하게 취급 — 상품명/재료명에 나타날
  단순 키워드로 바꿀 수 있는 위험도 있는 건강 정보면(예: "당뇨라서 단 거
  조심해야 해" → "설탕") explicit_exclusion 우선 고려, 애매하면
  soft_preference.
- value_priority/delivery_priority/cooking_frequency/household_notes/
  favorite_foods/usual_order_platform/inconveniences/additional_signals:
  soft_preference 우선 고려 (배제 근거로 쓰기엔 확신이 없는 성향 정보 —
  위 soft_preference 기준을 그대로 적용). usual_order_platform은 "평소
  습관"일 뿐 이번 요청의 명시적 플랫폼 지정이 아니므로 override_platform/
  retrieval로 쓰지 마세요.
이 섹션에서 온 신호는 source="session_smalltalk"로 분류하세요(아래
[source] 기준과 동일 — smalltalk_agent가 이미 이번 세션 대화에서
추출해둔 것이므로).

[source — 신호가 어느 입력 섹션에서 왔는지]
- "general_context": 아래 "장기 프로필 요약" 섹션에서 온 신호
- "purchase_history": 아래 "구매이력" 섹션에서 온 신호
- "session_smalltalk": 아래 "이번 세션 대화" 섹션 또는 "잡담에서 수집된
  정보" 섹션에서 온 신호
반드시 실제로 그 정보가 등장한 섹션을 그대로 쓰세요 — source가 우선순위
판단(Priority Resolver, Stage4)의 근거가 됩니다.

[routed_signals 순서]
"session_smalltalk" 소스인 신호들은 반드시 "이번 세션 대화"에 실제로
등장한 순서 그대로 routed_signals에 담으세요 (나중에 말한 것을 뒤에).
이 순서가 세션 내부에서 발화끼리 충돌할 때 "어느 게 더 최근인지" 판단
근거로 그대로 쓰입니다 — 별도 시각 정보 없이 이 순서만으로 판단하므로
순서를 임의로 바꾸면 안 됩니다.

[참고 — 아래 구매이력 중 만족도가 낮게 기록됐거나 메모가 부정적인 항목이
있다면 explicit_exclusion 후보로 고려하세요. 만족도/메모 정보가 아예 없는
항목은 특별히 취급하지 마세요.]

신호가 하나도 없으면 routed_signals는 빈 리스트로 반환하세요 (억지로
만들지 마세요).

# 장기 프로필 요약 (알레르기 등 안전 정보는 이미 별도 처리되어 여기 없음)
{profile_summary}

# 잡담(smalltalk_agent)에서 수집된 정보 — 구매이력과 무관하게 항상 참고
{smalltalk_profile_summary}

# 구매이력 통계 (집계본)
{general_preference_summary}

# 이번 키워드 관련 구매이력 (최대 5건)
{keyword_history_lines}

# 이번 세션 대화
{session_text}

# 이번 요청 키워드
{current_keywords}
"""
