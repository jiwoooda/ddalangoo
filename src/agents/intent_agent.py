"""
Intent Agent Node.

역할: 사용자 발화 → intent + slot 추출.
with_structured_output(Pydantic)으로 스키마를 강제해 누락 방지.
"""
import json
from typing import Literal, Optional
from pydantic import BaseModel, Field
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


class IntentOutput(BaseModel):
    intent: IntentType = Field(description="사용자 의도")
    keywords: list[str] = Field(default_factory=list, description="검색할 상품명/카테고리/브랜드")
    exclude_keywords: list[str] = Field(default_factory=list, description="제외할 브랜드/플랫폼/상품명")
    negative_constraints: list[str] = Field(default_factory=list, description="자연어 제외 조건")
    quantity: Optional[int] = Field(
        default=None,
        description=(
            "사용자가 명시적으로 말한 수량. 발화에 수량이 없으면 절대 임의로 1을 넣지 말고 null로 둘 것. "
            "단, pending_action=quantity_confirm일 때 수량 표현이 있으면 반드시 숫자로 채울 것. "
            "예: '두 개'→2, '세개요'→3, '하나만요'→1, '다섯 봉지'→5, '3개'→3, '3'→3"
        ),
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
        }

    result = {
        "intent": parsed.intent,
        "keywords": parsed.keywords or state.get("keywords") or [],
        "exclude_keywords": parsed.exclude_keywords,
        "negative_constraints": parsed.negative_constraints,
        "quantity": parsed.quantity if parsed.quantity is not None else state.get("quantity"),
        "condition": parsed.condition,
        "target_platforms": parsed.target_platforms,
        "override_platform": parsed.override_platform,
        "current_option_value": parsed.current_option_value,
        "address_text": parsed.address_text,
        "needs_clarification": parsed.needs_clarification,
        "clarification_reason": parsed.clarification_reason,
        "confidence": parsed.confidence if parsed.confidence > 0 else 0.9,
        "immediate_response": parsed.immediate_response,
        "last_agent": "intent_agent",
    }
    agent_logger.log_intent(user_input, stage, pending_action, result)
    return result
