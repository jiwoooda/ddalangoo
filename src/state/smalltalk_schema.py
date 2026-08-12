"""
SmalltalkProfileSchema — smalltalk_agent가 잡담에서 수집하는 구조화 프로필.

smalltalk_agent는 이 스키마를 채우기만 한다(수집기 역할) — soft_preference/
explicit_exclusion 같은 tier 분류는 하지 않는다. 분류는 context_agent가
profile에 누적된 이 값을 읽어서 RoutedSignal(routed_signal.py)로 판단한다.

additional_signals는 고정 필드 밖의 새로운 선호도를 담는 탈출구다 — 대화에서
나온 게 위 필드 어디에도 안 맞지만 분명히 취향/선호라고 판단되면 라벨을
자유롭게 붙여서 여기 넣는다. 카테고리를 미리 제한하지 않는다.
"""
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class AdditionalSignal(BaseModel):
    label: str = Field(description="무엇에 대한 선호인지 한 단어 라벨 (예: 선호 원산지, 포장 선호)")
    value: str = Field(description="실제 발언 내용/추출된 값")


class SmalltalkProfileSchema(BaseModel):
    food_dislikes: list[str] = Field(
        default_factory=list,
        description="알레르기는 아니지만 못 먹거나 싫어하는 음식/식감 (예: 매운 음식, 질긴 고기)",
    )
    value_priority: Optional[Literal["가성비", "품질·브랜드", "무관"]] = Field(
        default=None,
        description="가성비 vs 품질·브랜드 중 평소 더 중요하게 여기는 쪽. "
        "매핑 예시 — '싼 게 좋아요'/'가격부터 봐요'/'저렴한 걸로 사요' → 가성비. "
        "'좋은 걸로 사요'/'브랜드 있는 거 써요'/'비싸도 품질 좋은 거' → 품질·브랜드. "
        "발화에 명확한 방향이 없으면 절대 추측하지 말고 None으로 둘 것.",
    )
    delivery_priority: Optional[Literal["빠른배송", "배송비절약", "무관"]] = Field(
        default=None,
        description="배송 속도 vs 배송비 절약 중 평소 더 중요하게 여기는 쪽. "
        "매핑 예시 — '빠른 게 좋아요'/'배송 빨리 오면 좋겠어요'/'기다리는 거 싫어요' "
        "→ 빠른배송. '배송비 아까워요'/'천천히 와도 되니까 무료배송으로'/'배송비 "
        "아끼는 게 낫죠' → 배송비절약. 발화가 어느 방향인지 헷갈리면 절대 반대로 "
        "추측하지 말고 None으로 둘 것 — 특히 '빠른'/'빨리' 같은 속도 표현이 나오면 "
        "무조건 빠른배송 쪽이다.",
    )
    household_size: Optional[int] = Field(default=None, description="언급된 가구 인원수")
    household_notes: list[str] = Field(
        default_factory=list, description="가족구성/동거인/반려동물 등 생활 맥락 관련 언급"
    )
    cooking_frequency: Optional[Literal["자주", "가끔", "거의안함"]] = Field(
        default=None,
        description="직접 요리를 자주 하는지 vs 간편식/완제품을 더 선호하는지. "
        "매핑 예시 — '거의 매일 해먹어요'/'요리를 즐겨요' → 자주. '가끔 해먹어요'/"
        "'바쁠 때만요' → 가끔. '거의 안 해요'/'사 먹는 게 편해요'/'간편식 위주예요' "
        "→ 거의안함. 헷갈리면 None으로 둘 것.",
    )
    favorite_foods: list[str] = Field(
        default_factory=list, description="좋아하는 음식/식재료 (예: 어제 먹은 것에서 자연스럽게 드러난 것도 포함)",
    )
    usual_order_platform: Optional[str] = Field(
        default=None, description="평소 장보기/주문을 주로 어디서 하는지 (예: 쿠팡, 마켓컬리, 동네마트)",
    )
    health_notes: list[str] = Field(
        default_factory=list,
        description="알레르기·식이제한 이상으로 신경 쓰이는 건강 상태 (예: 당뇨, 혈압, 저염식 필요, 복용 중인 약)",
    )
    inconveniences: list[str] = Field(
        default_factory=list, description="기존 장보기/배달 경험에서 불편했던 점",
    )
    additional_signals: list[AdditionalSignal] = Field(default_factory=list)


SMALLTALK_PROFILE_FIELDS = (
    "food_dislikes", "value_priority", "delivery_priority",
    "household_size", "household_notes", "cooking_frequency",
    "favorite_foods", "usual_order_platform", "health_notes", "inconveniences",
    "additional_signals",
)


def format_smalltalk_profile(profile: Optional[dict[str, Any]]) -> str:
    """profile에 누적된 SmalltalkProfileSchema 값을 사람이 읽을 수 있는 텍스트로.

    두 곳에서 재사용한다:
    - context_agent._classify_context: tier2/tier3 분류 프롬프트에 "잡담에서
      수집된 정보" 섹션으로 (일반 profile_summary와 분리해서 tier1 안전정보와
      안 섞이게).
    - smalltalk_agent_node: 온보딩 대화 중(CHAT 프롬프트)에 "지금까지 파악된
      정보"로 보여줘서, LLM이 매 턴 대화 텍스트만으로 판단하지 않고 실제
      누적된 스키마 fill 상태를 보고 onboarding_complete를 판단하게 한다.
    """
    profile = profile or {}
    parts = []
    for field in SMALLTALK_PROFILE_FIELDS:
        value = profile.get(field)
        if not value:
            continue
        if field == "additional_signals":
            parts.append(", ".join(f"{s.get('label')}:{s.get('value')}" for s in value))
        elif isinstance(value, list):
            parts.append(f"{field}: {', '.join(str(v) for v in value)}")
        else:
            parts.append(f"{field}: {value}")
    return "; ".join(parts) or "없음"
