"""
Intent Agent Node.

역할: 사용자 발화 → intent + slot 추출 (JSON).
라우팅/검색/추천/결제는 하지 않는다.
"""
import json
import os
from typing import Any
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from src.state.schema import ShoppingState
from src.prompts.intent_prompt import INTENT_AGENT_PROMPT

_llm: ChatAnthropic | None = None


def _get_llm() -> ChatAnthropic:
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(
            model="claude-sonnet-4-6",
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

    return {
        "intent": parsed.get("intent"),
        "keywords": parsed.get("keywords") or [],
        "exclude_keywords": parsed.get("exclude_keywords") or [],
        "negative_constraints": parsed.get("negative_constraints") or [],
        "quantity": parsed.get("quantity") if parsed.get("quantity") is not None else state.get("quantity"),
        "condition": parsed.get("condition"),
        "target_platforms": parsed.get("target_platforms") or [],
        "override_platform": parsed.get("override_platform"),
        "current_option_value": parsed.get("current_option_value"),
        "address_text": parsed.get("address_text"),
        "needs_clarification": parsed.get("needs_clarification", False),
        "clarification_reason": parsed.get("clarification_reason"),
        "confidence": parsed.get("confidence", 0.0),
        "immediate_response": parsed.get("immediate_response"),
        "last_agent": "intent_agent",
    }
