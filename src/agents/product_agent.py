"""
Product Agent Node.

역할: 상품 비교/추천/설명/QA.
검색(search_product)과 결제는 하지 않는다.
"""
import json
from typing import Any
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from src.state.schema import ShoppingState
from src.prompts.product_prompt import PRODUCT_AGENT_PROMPT

_llm: ChatAnthropic | None = None


def _get_llm() -> ChatAnthropic:
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(
            model="claude-sonnet-4-6",
            temperature=0,
            max_tokens=1500,
        )
    return _llm


def _extract_user_question(state: ShoppingState) -> str | None:
    intent = state.get("intent")
    if intent != "ask":
        return None
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return msg.get("content")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role == "human":
                return getattr(msg, "content", None)
    return None


def product_agent_node(state: ShoppingState) -> dict:
    """
    Product Agent.
    역할: 상품 비교/랭킹/추천 + QA + explanation 생성 + pending_action 설정.
    검색과 결제 처리는 하지 않는다.
    """
    recommendation_context = state.get("recommendation_context") or {}
    intent = state.get("intent")
    user_question = _extract_user_question(state)

    prompt = PRODUCT_AGENT_PROMPT.format(
        search_results=json.dumps(state.get("search_results") or [], ensure_ascii=False),
        recommended_products=json.dumps(state.get("recommended_products") or [], ensure_ascii=False),
        selected_product=json.dumps(state.get("selected_product"), ensure_ascii=False),
        current_product_index=state.get("current_product_index", 0),
        condition=state.get("condition") or "null",
        quantity=state.get("quantity") or "null",
        keywords=json.dumps(state.get("keywords") or [], ensure_ascii=False),
        user_question=json.dumps(user_question, ensure_ascii=False),
        recommendation_context=json.dumps(recommendation_context, ensure_ascii=False),
        pending_action=json.dumps(state.get("pending_action"), ensure_ascii=False),
        intent=intent or "null",
    )

    llm = _get_llm()
    response = llm.invoke([HumanMessage(content=prompt)])
    content = response.content.strip()

    try:
        if "```" in content:
            import re
            m = re.search(r"```(?:json)?\s*([\s\S]+?)```", content)
            if m:
                content = m.group(1).strip()
            else:
                # 닫는 ``` 없이 잘린 경우 → { 부터 추출
                brace = content.find("{")
                if brace != -1:
                    content = content[brace:]
        parsed: dict[str, Any] = json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        print(f"[product_agent] parse error: {e}\ncontent: {content[:200]}")
        return {
            "error": "product_agent_parse_error",
            "stage": "idle",
            "last_agent": "product_agent",
        }

    result: dict[str, Any] = {
        "last_agent": "product_agent",
        "error": parsed.get("error"),
    }

    if parsed.get("selected_product"):
        result["selected_product"] = parsed["selected_product"]
        result["product_url"] = (
            parsed["selected_product"].get("product_url")
            or parsed["selected_product"].get("url")
        )

    if parsed.get("recommended_products") is not None:
        result["recommended_products"] = parsed["recommended_products"]

    if parsed.get("current_product_index") is not None:
        result["current_product_index"] = parsed["current_product_index"]

    if parsed.get("explanation"):
        result["explanation"] = parsed["explanation"]

    # answer(QA 답변)는 explanation으로 올려서 respond_node가 출력하게
    if not parsed.get("explanation") and parsed.get("answer"):
        result["explanation"] = parsed["answer"]

    if parsed.get("pending_action"):
        result["pending_action"] = parsed["pending_action"]

    stage = parsed.get("stage", "product_confirming")
    result["stage"] = stage

    return result
