"""
Product Agent Node.

역할: 상품 비교/추천/설명/QA.
검색(search_product)과 결제는 하지 않는다.

2단계 처리:
  Phase 1 (첫 검색): rank_products 툴 호출 → 후보 전체 순위화 (in-process)
  Phase 2:           순위 1위(또는 next) 상품에 대한 explanation 생성

next/deny 재호출 시 Phase 1 스킵 — 기존 recommended_products 재사용.
"""
import json
from typing import Any
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool as lc_tool

from src.state.schema import ShoppingState
from src.prompts.product_prompt import (
    PRODUCT_RANK_PROMPT,
    PRODUCT_EXPLAIN_PROMPT,
    PRODUCT_QA_PROMPT,
)
from src.utils.agent_logger import agent_logger

_llm: ChatAnthropic | None = None


def _get_llm() -> ChatAnthropic:
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(
            model="claude-sonnet-4-6",
            temperature=0,
            max_tokens=800,
        )
    return _llm


def _format_products(products: list[dict[str, Any]]) -> str:
    """후보 상품을 LLM이 읽기 쉬운 텍스트로 변환."""
    if not products:
        return "후보 상품 없음"
    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lines = []
    for i, p in enumerate(products):
        label = labels[i] if i < len(labels) else str(i)
        name = p.get("product_name", "이름 없음")
        price = p.get("price")
        price_str = f"{price:,}원" if price else "가격 미확인"
        delivery = p.get("delivery") or ""
        rating = p.get("rating")
        review = p.get("review_count")
        platform = p.get("platform", "")

        parts = [f"[{label}] {name}", price_str]
        if delivery:
            parts.append(str(delivery))
        if rating:
            parts.append(f"⭐{rating}")
        if review:
            parts.append(f"리뷰 {review:,}개")
        if platform:
            parts.append(f"({platform})")
        lines.append("  ".join(parts))
    return "\n".join(lines)


def _format_preference(preference_context: dict[str, Any]) -> str:
    """선호도 컨텍스트를 프롬프트용 텍스트로 변환."""
    if not preference_context or not preference_context.get("summary"):
        return "선호 정보 없음 (구매이력 부족)"
    lines = [preference_context["summary"]]
    keyword_summary = preference_context.get("keyword_summary") or ""
    if keyword_summary:
        lines.append(f"키워드 관련 선호: {keyword_summary}")
    return "\n".join(lines)


def _make_rank_tool(candidates: list[dict[str, Any]]):
    """
    candidates를 레이블(A, B, C...)로 참조하는 rank_products 툴 생성.
    LLM이 레이블 순서를 지정하면 실제 product 객체 리스트로 변환한다.
    """
    label_map = {chr(ord("A") + i): p for i, p in enumerate(candidates[:26])}

    @lc_tool
    def rank_products(ranked_labels: list[str], filtered_out_labels: list[str] = []) -> str:
        """
        후보 상품을 순위대로 정렬한다.
        ranked_labels: 1위부터 순서대로 레이블 리스트 (예: ["C", "A", "B"])
        filtered_out_labels: 키워드와 상품군이 달라 제외할 레이블 (예: ["D", "E"])
        """
        ranked = [
            label_map[lbl.upper()]
            for lbl in ranked_labels
            if lbl.upper() in label_map
        ]
        print(
            f"[product_agent:tool] 순위: {[l.upper() for l in ranked_labels]} "
            f"제외: {[l.upper() for l in filtered_out_labels]} → {len(ranked)}개"
        )
        return json.dumps(ranked, ensure_ascii=False)

    return rank_products


def _generate_explanation(
    product: dict[str, Any],
    keywords: list[str],
    condition: str | None,
    preference_context: dict[str, Any] | None = None,
) -> str:
    """특정 상품에 대한 음성용 explanation 생성."""
    prompt = PRODUCT_EXPLAIN_PROMPT.format(
        product_json=json.dumps(product, ensure_ascii=False),
        keywords=json.dumps(keywords, ensure_ascii=False),
        condition=condition or "없음",
        preference_context=_format_preference(preference_context or {}),
    )
    return _get_llm().invoke([HumanMessage(content=prompt)]).content.strip()


def _extract_user_question(state: ShoppingState) -> str | None:
    if state.get("intent") != "ask":
        return None
    for msg in reversed(state.get("messages") or []):
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
    Phase 1 (첫 검색): rank_products 툴로 후보 전체 순위화
    Phase 2:           순위 상품 explanation 생성
    next/deny:         Phase 1 스킵, 기존 ranked list에서 다음 항목 설명만 생성
    """
    recommendation_context = state.get("recommendation_context") or {}
    preference_context = recommendation_context.get("preference_context") or {}
    intent = state.get("intent")
    keywords = state.get("keywords") or []
    condition = state.get("condition")
    current_idx = state.get("current_product_index") or 0
    existing_ranked = state.get("recommended_products") or []

    # ── QA (ask intent) ──
    if intent == "ask":
        user_question = _extract_user_question(state)
        target = state.get("selected_product") or (
            existing_ranked[current_idx] if existing_ranked else None
        )
        if not target or not user_question:
            return {"stage": "product_confirming", "last_agent": "product_agent", "error": None}
        answer = _get_llm().invoke([HumanMessage(content=PRODUCT_QA_PROMPT.format(
            product_json=json.dumps(target, ensure_ascii=False),
            question=user_question,
        ))]).content.strip()
        return {
            "explanation": answer,
            "stage": "product_confirming",
            "last_agent": "product_agent",
            "error": None,
        }

    # ── next/deny ──
    if intent in ("next", "deny") and existing_ranked:
        # condition이 새로 지정됐으면 기존 pool을 재랭킹 (platform_agent 재호출 없음)
        if condition:
            rank_tool = _make_rank_tool(existing_ranked)
            rank_response = _get_llm().bind_tools([rank_tool]).invoke([
                HumanMessage(content=PRODUCT_RANK_PROMPT.format(
                    formatted_products=_format_products(existing_ranked),
                    preference_context=_format_preference(preference_context),
                    keywords=json.dumps(keywords, ensure_ascii=False),
                    condition=condition,
                ))
            ])
            reranked = existing_ranked  # fallback
            if rank_response.tool_calls:
                tc = rank_response.tool_calls[0]
                try:
                    result = json.loads(rank_tool.invoke(tc["args"]))
                    if result:
                        reranked = result
                except Exception as e:
                    print(f"[product_agent] 재랭킹 실패, fallback 사용: {e}")

            top_product = reranked[0] if reranked else None
            if not top_product:
                return {"stage": "idle", "error": "no_relevant_products", "last_agent": "product_agent"}

            explanation = _generate_explanation(top_product, keywords, condition, preference_context)
            agent_logger.log_product_agent(
                {"intent": intent, "rerank": True, "condition": condition},
                {"selected_product": top_product},
            )
            return {
                "selected_product": top_product,
                "product_url": top_product.get("product_url"),
                "recommended_products": reranked,
                "current_product_index": 0,
                "explanation": explanation,
                "pending_action": {"type": "product_confirm"},
                "stage": "product_confirming",
                "quantity": None,
                "last_agent": "product_agent",
                "error": None,
            }

        # 순수 next/deny — 다음 항목 설명만
        next_idx = current_idx + 1
        if next_idx >= len(existing_ranked):
            return {
                "stage": "searching",
                "error": "no_more_products",
                "last_agent": "product_agent",
                "pending_action": {
                    "type": "no_more_products",
                    "message": "더 이상 추천할 상품이 없어요. 다른 검색어로 찾아볼까요?",
                },
            }
        next_product = existing_ranked[next_idx]
        explanation = _generate_explanation(next_product, keywords, condition, preference_context)
        agent_logger.log(f"[product_agent] next → idx={next_idx}: '{next_product.get('product_name')}'")
        agent_logger.log(f"[product_agent] 설명문: {explanation}")
        agent_logger.log_product_agent(
            {"intent": intent, "next_idx": next_idx},
            {"selected_product": next_product, "explanation": explanation},
        )
        return {
            "selected_product": next_product,
            "product_url": next_product.get("product_url"),
            "recommended_products": existing_ranked,
            "current_product_index": next_idx,
            "explanation": explanation,
            "pending_action": {"type": "product_confirm"},
            "stage": "product_confirming",
            "quantity": None,
            "last_agent": "product_agent",
            "error": None,
        }

    # ── 첫 검색: Phase 1 (ranking) + Phase 2 (explain) ──
    candidates = state.get("search_results") or existing_ranked
    if not candidates:
        return {"stage": "idle", "error": "no_candidates", "last_agent": "product_agent"}

    agent_logger.log(
        f"[product_agent] Phase1 랭킹 시작 | 후보 {len(candidates)}개  keywords={keywords}  condition={condition}"
    )
    pref_summary = (preference_context.get("summary") or "")[:80]
    pref_kw = (preference_context.get("keyword_summary") or "")[:80]
    if pref_summary:
        agent_logger.log(f"[product_agent] 일반선호도 주입: {pref_summary}")
    if pref_kw:
        agent_logger.log(f"[product_agent] 키워드선호도 주입: {pref_kw}")

    # Phase 1: rank_products 툴 호출 (in-process)
    rank_tool = _make_rank_tool(candidates)
    rank_response = _get_llm().bind_tools([rank_tool]).invoke([
        HumanMessage(content=PRODUCT_RANK_PROMPT.format(
            formatted_products=_format_products(candidates),
            preference_context=_format_preference(preference_context),
            keywords=json.dumps(keywords, ensure_ascii=False),
            condition=condition or "없음",
        ))
    ])

    ranked_products = candidates  # fallback: 원래 순서
    if rank_response.tool_calls:
        tc = rank_response.tool_calls[0]
        try:
            result = json.loads(rank_tool.invoke(tc["args"]))
            if result:
                ranked_products = result
                top_names = [p.get("product_name", "?")[:30] for p in ranked_products[:3]]
                agent_logger.log(f"[product_agent] 랭킹 결과 TOP3: {top_names}")
        except Exception as e:
            agent_logger.log(f"[product_agent] rank_tool 실패 fallback: {e}")
            print(f"[product_agent] rank_tool 실패, fallback 사용: {e}")

    top_product = ranked_products[0] if ranked_products else None
    if not top_product:
        return {"stage": "idle", "error": "no_relevant_products", "last_agent": "product_agent"}

    agent_logger.log(
        f"[product_agent] 1위 선택: '{top_product.get('product_name')}' "
        f"({top_product.get('price'):,}원  {top_product.get('platform')})"
        if top_product.get('price') else
        f"[product_agent] 1위 선택: '{top_product.get('product_name')}' ({top_product.get('platform')})"
    )

    # Phase 2: explanation 생성
    explanation = _generate_explanation(top_product, keywords, condition, preference_context)
    agent_logger.log(f"[product_agent] 설명문: {explanation}")

    agent_logger.log_product_agent(
        {"intent": intent, "candidates": len(candidates), "ranked": len(ranked_products)},
        {"selected_product": top_product, "explanation": explanation},
    )
    return {
        "selected_product": top_product,
        "product_url": top_product.get("product_url"),
        "recommended_products": ranked_products,
        "current_product_index": 0,
        "explanation": explanation,
        "pending_action": {"type": "product_confirm"},
        "stage": "product_confirming",
        "quantity": None,
        "last_agent": "product_agent",
        "error": None,
    }
