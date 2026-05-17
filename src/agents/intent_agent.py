"""
Intent Agent Node.

역할: 사용자 발화 → intent + slot 추출 (JSON).
라우팅/검색/추천/결제는 하지 않는다.
"""
import json
import os
import re
from typing import Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.state.schema import ShoppingState
from src.prompts.intent_prompt import INTENT_AGENT_PROMPT

_KR_NUMBER_MAP = {
    "하나": 1, "한": 1, "일": 1,
    "둘": 2, "두": 2, "이": 2,
    "셋": 3, "세": 3, "삼": 3,
    "넷": 4, "네": 4, "사": 4,
    "다섯": 5, "오": 5,
    "여섯": 6, "육": 6,
    "일곱": 7, "칠": 7,
    "여덟": 8, "팔": 8,
    "아홉": 9, "구": 9,
    "열": 10, "십": 10,
}


def _extract_korean_quantity(text: str) -> int | None:
    """'두 개', '3개', '세개' 등에서 숫자를 추출한다."""
    # 아라비아 숫자 + 개/명/봉 등
    m = re.search(r"(\d+)\s*(?:개|명|봉|팩|박스|캔|병|그램|kg|L)?", text)
    if m:
        return int(m.group(1))
    # 한국어 숫자 + 개/명 등
    for kr, num in _KR_NUMBER_MAP.items():
        pattern = rf"{kr}\s*(?:개|명|봉|팩|박스|캔|병)?"
        if re.search(pattern, text):
            return num
    return None

_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=512,
        )
    return _llm


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

    prompt = INTENT_AGENT_PROMPT.format(
        user_input=user_input,
        stage=stage,
        pending_action=json.dumps(pending_action, ensure_ascii=False) if pending_action else "null",
        context="",
    )

    llm = _get_llm()
    response = llm.invoke([SystemMessage(content=prompt)])
    content = response.content.strip()

    try:
        # ```json ... ``` 블록 제거
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        parsed: dict[str, Any] = json.loads(content)
    except json.JSONDecodeError:
        parsed = {
            "intent": "unclear",
            "keywords": [],
            "exclude_keywords": [],
            "negative_constraints": [],
            "quantity": None,
            "condition": None,
            "target_platforms": [],
            "override_platform": None,
            "current_option_value": None,
            "address_text": None,
            "needs_clarification": True,
            "clarification_reason": "응답 파싱 오류",
            "confidence": 0.0,
            "immediate_response": "다시 말씀해 주세요.",
        }

    # quantity 추출 실패 시 사용자 입력에서 직접 파싱 (quantity_confirm 대기 중인 경우)
    quantity = parsed.get("quantity")
    if quantity is None:
        pending_type = (pending_action or {}).get("type") if pending_action else None
        if pending_type == "quantity_confirm":
            quantity = _extract_korean_quantity(user_input)
        if quantity is None:
            quantity = state.get("quantity")

    return {
        "intent": parsed.get("intent"),
        "keywords": parsed.get("keywords") or state.get("keywords") or [],
        "exclude_keywords": parsed.get("exclude_keywords") or [],
        "negative_constraints": parsed.get("negative_constraints") or [],
        "quantity": quantity,
        "condition": parsed.get("condition"),
        "target_platforms": parsed.get("target_platforms") or [],
        "override_platform": parsed.get("override_platform"),
        "current_option_value": parsed.get("current_option_value"),
        "address_text": parsed.get("address_text"),
        "needs_clarification": parsed.get("needs_clarification", False),
        "clarification_reason": parsed.get("clarification_reason"),
        "confidence": parsed.get("confidence") or 0.9,
        "immediate_response": parsed.get("immediate_response"),
        "last_agent": "intent_agent",
    }
