"""
Intent Agent Node.

역할: 사용자 발화 → intent + slot 추출.
with_structured_output(Pydantic)으로 스키마를 강제해 누락 방지.
"""
import json
import re
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from src.state.schema import ShoppingState
from src.prompts.intent_prompt import INTENT_AGENT_PROMPT
from src.utils.agent_logger import agent_logger

IntentType = Literal[
    "buy", "reorder", "confirm", "deny", "next", "refine",
    "compare_platforms", "quantity_change", "address_change",
    "option_select", "ask", "cancel", "unclear",
]

ConditionType = Literal["최저가", "가성비", "빠른배송", "인기순", "무료배송", "리뷰좋은"]

_KR_NUM = {
    "하나": 1, "한": 1, "일": 1,
    "둘": 2, "두": 2,
    "셋": 3, "세": 3,
    "넷": 4, "네": 4,
    "다섯": 5, "오": 5,
    "여섯": 6, "육": 6,
    "일곱": 7, "칠": 7,
    "여덟": 8, "팔": 8,
    "아홉": 9, "구": 9,
    "열": 10, "십": 10,
    "스물": 20, "스무": 20, "이십": 20,
}

_PAYMENT_CONFIRM_SHORT_TEXTS = {
    "응",
    "네",
    "그래",
    "좋아",
    "맞아",
    "결제",
    "결제할래",
    "결제해줘",
    "이제결제",
    "이제결제할래",
}
_AMBIGUOUS_CONFIRM_TEXTS = {"음", "음.", "음...", "으음", "흠", "어", "어..."}
_PAYMENT_CONFIRM_TOKENS = ("결제", "계산", "네이버", "페이")
_ADD_PRODUCT_TOKENS = (
    "담아",
    "담아줘",
    "추가",
    "추가해",
    "추가해줘",
    "사줘",
    "살래",
    "살게",
    "구매",
    "넣어",
    "넣어줘",
)
_PRODUCT_REQUEST_TOKENS = _ADD_PRODUCT_TOKENS + ("사고싶", "살게요", "볼게", "볼래", "찾아")
_GENERIC_CONTINUE_KEYWORDS = {
    "다른",
    "다른거",
    "다른것",
    "하나더",
    "한개더",
    "더",
    "또",
    "추가",
    "쇼핑",
}


def _parse_quantity(v) -> Optional[int]:
    """아라비아 숫자 또는 한국어 수량 표현 → int. 파싱 불가면 None."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    text = str(v).strip()
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    for kr, num in sorted(_KR_NUM.items(), key=lambda x: -len(x[0])):
        if kr in text:
            return num
    return None


def _parse_explicit_quantity(v) -> Optional[int]:
    """상품명 안의 글자가 아니라 '한 개/2개'처럼 명시된 수량만 파싱한다."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    text = str(v).strip()
    text = re.sub(
        r"(담아줘|담아|추가해줘|추가해|추가|사줘|사고\s*싶어|살래|살게요|살게|구매해줘|구매|넣어줘|넣어|볼게요|볼게|볼래|찾아줘|찾아|주세요|줘|해줘)\s*$",
        "",
        text,
    ).strip()
    digit_match = re.search(r"(\d+)\s*(개|병|팩|봉|상자|박스|개만|만)\s*$", text)
    if digit_match:
        return int(digit_match.group(1))
    for kr, num in sorted(_KR_NUM.items(), key=lambda x: -len(x[0])):
        if re.search(fr"{re.escape(kr)}\s*(개|병|팩|봉|상자|박스|개만|만)?\s*$", text):
            return num
    return None


def _compact_text(text: str) -> str:
    """의도 판별용으로 공백을 제거한다."""
    return re.sub(r"\s+", "", text.strip())


def _looks_like_payment_confirmation(text: str) -> bool:
    """장바구니 선택 단계에서 결제로 넘어가도 되는 발화인지 판별한다."""
    compact = _compact_text(text)
    if compact in _PAYMENT_CONFIRM_SHORT_TEXTS:
        return True
    return any(token in compact for token in _PAYMENT_CONFIRM_TOKENS)


def _looks_ambiguous_confirmation(text: str) -> bool:
    """결제 단계에서 바로 확정하면 위험한 짧은 망설임 표현인지 판별한다."""
    return _compact_text(text) in _AMBIGUOUS_CONFIRM_TEXTS


def _extract_continue_shopping_keyword(text: str) -> Optional[str]:
    """
    "결제할까요, 다른 것도 보실래요?" 다음 발화에서 새 상품명을 뽑는다.

    이 단계의 "그래"는 결제 진행이지만, "오이도 담아줘"는 새 검색으로 가야 한다.
    LLM이 pending action 때문에 confirm으로 오판해도 라우터가 쓸 keywords를 안정적으로 만든다.
    """
    return _extract_product_keyword(text, require_request_token=True)


def _extract_product_keyword(text: str, *, require_request_token: bool) -> Optional[str]:
    """후속 쇼핑 발화에서 상품명 후보를 추출한다."""
    compact = _compact_text(text)
    if not compact or _looks_like_payment_confirmation(text):
        return None
    if require_request_token and not any(token in compact for token in _PRODUCT_REQUEST_TOKENS):
        return None

    cleaned = text.strip()
    cleaned = re.sub(r"^(그거\s*말고|그건\s*말고|말고|다른\s*거\s*말고)\s*", "", cleaned).strip()
    # 문장 끝의 구매/추가 동사를 먼저 제거한다.
    cleaned = re.sub(
        r"(담아줘|담아|추가해줘|추가해|추가|사줘|사고\s*싶어|살래|살게요|살게|구매해줘|구매|넣어줘|넣어|볼게요|볼게|볼래|찾아줘|찾아|주세요|줘|해줘)\s*$",
        "",
        cleaned,
    ).strip()
    # 명시 수량과 보조 표현은 상품명 후보에서 제외한다.
    cleaned = re.sub(
        r"(\d+\s*개|한\s*개|하나|두\s*개|둘|세\s*개|셋|만|좀|더)\s*$",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # 끝 조사 제거: 오이도 → 오이, 계란을 → 계란
    cleaned = re.sub(r"(도|은|는|이|가|을|를)$", "", cleaned).strip()

    if not cleaned:
        return None
    if _compact_text(cleaned) in _GENERIC_CONTINUE_KEYWORDS:
        return None
    return cleaned


class IntentOutput(BaseModel):
    intent: IntentType = Field(description="사용자 의도")
    keywords: list[str] = Field(default_factory=list, description="검색할 상품명/카테고리/브랜드")
    exclude_keywords: list[str] = Field(default_factory=list, description="제외할 브랜드/플랫폼/상품명")
    negative_constraints: list[str] = Field(default_factory=list, description="자연어 제외 조건")
    quantity: Optional[int] = Field(
        default=None,
        description="명시된 수량만 정수로. 없으면 null. 한국어 수량(한·두·세…)도 정수로 변환.",
        json_schema_extra={"examples": [1, 2, 3, 5, 10]},
    )

    condition: Optional[ConditionType] = Field(default=None, description="검색 조건")
    target_platforms: list[str] = Field(default_factory=list, description="비교 대상 플랫폼 목록")
    override_platform: Optional[str] = Field(default=None, description="명시적으로 지정한 단일 플랫폼")
    current_option_value: Optional[str] = Field(default=None, description="명시된 상품 옵션값")
    address_text: Optional[str] = Field(default=None, description="사용자가 말한 배송지 텍스트")
    needs_clarification: bool = Field(default=False, description="추가 정보가 필요하면 true")
    clarification_reason: Optional[str] = Field(default=None, description="needs_clarification=true일 때 이유")
    confidence: float = Field(
        default=0.95,
        description="의도 해석 확신도 0.0~1.0. 명확하면 0.9 이상, 모호하면 0.5~0.8, 불분명하면 0.3 이하",
    )
    immediate_response: str = Field(default="", description="음성 출력용 한 문장 응답")

    @field_validator("quantity", mode="before")
    @classmethod
    def coerce_quantity(cls, v):
        return _parse_quantity(v)


_llm: ChatOpenAI | None = None
_structured_llm = None


def _get_llm():
    global _llm, _structured_llm
    if _llm is None:
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        _structured_llm = _llm.with_structured_output(IntentOutput)
    return _structured_llm


def _extract_user_input(state: ShoppingState) -> str:
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return msg.get("content", "")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role == "human":
                return getattr(msg, "content", "")
    return ""


def intent_agent_node(state: ShoppingState) -> dict:
    """
    Intent Agent 호출.
    반환값:
    - intent, keywords, exclude_keywords, negative_constraints
    - quantity, condition, target_platforms, override_platform
    - current_option_value, address_text
    - needs_clarification, clarification_reason, confidence, immediate_response
    """
    user_input = _extract_user_input(state)
    stage = state.get("stage", "idle")
    pending_action = state.get("pending_action")
    
    pending_type = pending_action.get("type") if isinstance(pending_action, dict) else "null"

    prompt = INTENT_AGENT_PROMPT.format(
        user_input=user_input,
        stage=stage,
        pending_action=pending_type,
        context="",
    )

    llm = _get_llm()
    try:
        parsed: IntentOutput = llm.invoke([SystemMessage(content=prompt)])
    except Exception as e:
        print(f"[intent_agent] structured output error: {e}")
        return {
            "intent": "unclear",
            "keywords": state.get("keywords") or [],
            "exclude_keywords": [],
            "negative_constraints": [],
            "quantity": state.get("quantity"),
            "condition": None,
            "target_platforms": [],
            "override_platform": None,
            "current_option_value": None,
            "address_text": None,
            "needs_clarification": True,
            "clarification_reason": "응답 파싱 오류",
            "confidence": 0.0,
            "immediate_response": "다시 말씀해 주세요.",
            "last_agent": "intent_agent",
            "tool_calls": None,
            "tool_results": None,
        }

    # quantity_confirm 대기 중엔 직접 파싱 우선 (LLM이 상품명 숫자에 혼동될 수 있음)
    quantity = parsed.quantity
    if pending_type == "quantity_confirm":
        direct = _parse_quantity(user_input)
        if direct is not None:
            quantity = direct

    intent = parsed.intent
    keywords = parsed.keywords or state.get("keywords") or []
    needs_clarification = parsed.needs_clarification
    clarification_reason = parsed.clarification_reason
    confidence = parsed.confidence if parsed.confidence > 0 else 0.9

    # continue_shopping에서는 "그래"와 "오이도 담아줘"가 완전히 다른 길이다.
    # 새 상품명이 보이면 이전 selected_product를 재사용하지 않도록 buy intent로 보정한다.
    if pending_type == "continue_shopping":
        continue_keyword = _extract_continue_shopping_keyword(user_input)
        if continue_keyword:
            intent = "buy"
            keywords = [continue_keyword]
            needs_clarification = False
            clarification_reason = None
            confidence = max(confidence, 0.95)
            direct_quantity = _parse_explicit_quantity(user_input)
            if direct_quantity is not None:
                quantity = direct_quantity
        elif _looks_like_payment_confirmation(user_input):
            intent = "confirm"
            keywords = []
            needs_clarification = False
            clarification_reason = None
            confidence = max(confidence, 0.95)

    # "무엇을 구매하실까요?" 다음 입력은 새 상품 요청으로 해석한다.
    # 예: "찌개 두부 하나" → keyword="찌개 두부", quantity=1
    if pending_type == "what_to_buy":
        what_to_buy_keyword = _extract_product_keyword(user_input, require_request_token=False)
        if what_to_buy_keyword:
            intent = "buy"
            keywords = [what_to_buy_keyword]
            needs_clarification = False
            clarification_reason = None
            confidence = max(confidence, 0.95)
            direct_quantity = _parse_explicit_quantity(user_input)
            if direct_quantity is not None:
                quantity = direct_quantity
        elif _looks_like_payment_confirmation(user_input):
            intent = "confirm"
            keywords = []
            needs_clarification = False
            clarification_reason = None
            confidence = max(confidence, 0.95)

    # 추천/수량 확인 중에도 "그거 말고 수박 사줘"처럼 새 상품명이 나오면
    # 현재 selected_product/recommendation_item_id를 수락한 것으로 보면 안 된다.
    if pending_type in ("product_confirm", "quantity_confirm"):
        replacement_keyword = _extract_product_keyword(user_input, require_request_token=True)
        if replacement_keyword:
            intent = "buy"
            keywords = [replacement_keyword]
            needs_clarification = False
            clarification_reason = None
            confidence = max(confidence, 0.95)
            direct_quantity = _parse_explicit_quantity(user_input)
            quantity = direct_quantity

    if pending_type == "payment_method_confirm" and _looks_ambiguous_confirmation(user_input):
        intent = "unclear"
        keywords = []
        needs_clarification = True
        clarification_reason = "결제 진행 여부가 명확하지 않습니다."
        confidence = 0.4
        quantity = None

    # 새 구매 탐색 intent에서는 이전 state 수량 인계 금지
    # (이전 상품 구매 때 남은 quantity가 새 상품에 그대로 쓰이는 문제 방지)
    _new_search_intents = {"buy", "reorder", "refine", "compare_platforms"}
    if quantity is None and intent not in _new_search_intents:
        quantity = state.get("quantity")

    result = {
        "intent": intent,
        "keywords": keywords,
        "exclude_keywords": parsed.exclude_keywords,
        "negative_constraints": parsed.negative_constraints,
        "quantity": quantity,
        "condition": parsed.condition,
        "target_platforms": parsed.target_platforms,
        "override_platform": parsed.override_platform,
        "current_option_value": parsed.current_option_value,
        "address_text": parsed.address_text,
        "needs_clarification": needs_clarification,
        "clarification_reason": clarification_reason,
        "confidence": confidence,
        "immediate_response": parsed.immediate_response,
        "last_agent": "intent_agent",
        "tool_calls": None,
        "tool_results": None,
    }
    agent_logger.log_intent(user_input, stage, pending_action, result)
    return result
