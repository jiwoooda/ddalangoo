"""
Context Agent Node.

역할:
  [Context Loading]  buy/refine/compare_platforms → 사용자 프로필/구매이력/선호 조회
  [Post-Payment]     stage == "completed" → 구매이력 저장 + 선호도 캐시 무효화 + 대화 요약
"""
from typing import Any, Optional
from langgraph.store.base import BaseStore
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.utils.agent_logger import agent_logger
from src.state.schema import ShoppingState
from src.prompts.context_prompt import CONTEXT_CLASSIFICATION_PROMPT
from src.tools import db_client
from src.tools.mock_tools import (
    mock_get_preference_memory,
    mock_vector_search_personal,
    mock_vector_search_collective,
)

PERSONAL_VECTOR_THRESHOLD = 20


class ContextClassificationLLM(BaseModel):
    """
    Context Agent 구조화 출력. safety_constraints(알레르기 등)는 여기 없다 —
    프로필에서 코드로 직접 채워서, LLM이 안전 정보를 중복/변형 생성하지
    않도록 한다.
    """
    keyword_additions: list[str] = Field(default_factory=list)
    exclude_additions: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)

_context_llm = None


def _get_llm():
    global _context_llm
    if _context_llm is None:
        try:
            from configs.llm_config import get_llm
            _context_llm = get_llm("context", temperature=0, max_tokens=400)
        except Exception:
            from langchain_anthropic import ChatAnthropic
            _context_llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0, max_tokens=400)
    return _context_llm


# ── DB 접근은 전부 db_client(mock/real 모드 전환)를 경유한다 ────────────

def _fetch_purchase_histories(user_id: str) -> list[dict[str, Any]]:
    result = db_client.get_purchase_histories(user_id)
    agent_logger.log(f"[context_agent] 구매이력 로드: {len(result)}건 (user_id={user_id})")
    return result


def _fetch_user_from_db(user_id: str) -> dict[str, Any] | None:
    return db_client.get_user(user_id)


def _fetch_default_address_for_context(user_id: str) -> dict[str, Any] | None:
    return db_client.get_default_address(user_id)


def _save_purchase_history_from_completed(user_id: str, completed_purchase: dict[str, Any]) -> None:
    order_id = completed_purchase.get("order_id")
    if not order_id:
        agent_logger.log("[context_agent] 구매이력 저장 스킵: order_id 없음")
        return
    db_client.save_purchase_history_from_completed(user_id, completed_purchase)
    agent_logger.log(f"[context_agent] 구매이력 저장 완료 (order_id={order_id})")


def _invalidate_preference_cache(user_id: str) -> None:
    db_client.invalidate_purchase_derived_preferences(user_id)
    agent_logger.log(f"[context_agent] 선호도 캐시 무효화 완료 (user_id={user_id})")


# ── 선호도 계산 ─────────────────────────────────────────────────

def _merge_recommendation_results(
    keyword_results: list[dict[str, Any]],
    personal_vector_results: list[dict[str, Any]],
    collective_vector_results: list[dict[str, Any]],
    intent: Optional[str] = None,
) -> list[dict[str, Any]]:
    merged = []
    seen: set = set()
    sources = [
        ("personal_vector", personal_vector_results),
        ("keyword", keyword_results),
        ("collective_vector", collective_vector_results),
    ]
    for source, results in sources:
        for item in results:
            key = item.get("product_url") or item.get("product_name") or item.get("id")
            if not key or key in seen:
                continue
            item = dict(item)
            item["_memory_source"] = source
            merged.append(item)
            seen.add(key)
    return merged[:10]


def _compute_general_preference(histories: list[dict[str, Any]]) -> dict[str, Any]:
    brand_counts: dict[str, int] = {}
    prices: list[int] = []
    platform_counts: dict[str, int] = {}
    product_counts: dict[str, int] = {}

    for h in histories:
        if b := h.get("brand"):
            brand_counts[b] = brand_counts.get(b, 0) + 1
        if p := h.get("price_at_purchase"):
            prices.append(int(p))
        if pl := h.get("platform"):
            platform_counts[pl] = platform_counts.get(pl, 0) + 1
        if n := h.get("product_name"):
            product_counts[n] = product_counts.get(n, 0) + 1

    preferred_brands = sorted(
        [{"brand": b, "count": c} for b, c in brand_counts.items()],
        key=lambda x: -x["count"],
    )[:5]

    price_range: dict[str, int] = {}
    if prices:
        price_range = {"avg": sum(prices) // len(prices), "min": min(prices), "max": max(prices)}

    repurchase_patterns = [
        name for name, count in sorted(product_counts.items(), key=lambda x: -x[1]) if count >= 2
    ][:5]

    preferred_platform = max(platform_counts, key=platform_counts.get) if platform_counts else None

    parts: list[str] = []
    if preferred_brands:
        parts.append("자주 구매한 브랜드: " + ", ".join(b["brand"] for b in preferred_brands[:3]))
    if price_range:
        parts.append(f"평균 구매가: {price_range['avg']:,}원")
    if repurchase_patterns:
        parts.append("재구매 상품: " + ", ".join(repurchase_patterns[:3]))
    if preferred_platform:
        parts.append(f"주로 이용 플랫폼: {preferred_platform}")

    return {
        "preferred_brands": preferred_brands,
        "price_range": price_range,
        "repurchase_patterns": repurchase_patterns,
        "preferred_platform": preferred_platform,
        "summary": ". ".join(parts) if parts else "",
    }


def _generate_llm_summary(preference: dict[str, Any], keyword_history: Optional[list] = None) -> str:
    try:
        brands = ", ".join(b["brand"] for b in (preference.get("preferred_brands") or [])[:3])
        pr = preference.get("price_range") or {}
        repurchase = ", ".join((preference.get("repurchase_patterns") or [])[:3])
        platform = preference.get("preferred_platform") or ""

        prompt = (
            "다음은 쇼핑 앱 사용자의 구매이력 통계입니다. "
            "이 데이터를 바탕으로 상품 추천에 활용할 수 있는 간결한 선호도 요약을 2~3문장으로 작성하세요. "
            "자연스러운 한국어로 작성하고, 추천 기준이 될 핵심 특성(브랜드 성향, 가격대, 재구매 패턴, 선호 플랫폼)을 포함하세요.\n\n"
            f"- 선호 브랜드: {brands or '없음'}\n"
            f"- 평균 구매가: {pr.get('avg', 0):,}원 (범위: {pr.get('min', 0):,}~{pr.get('max', 0):,}원)\n"
            f"- 재구매 상품: {repurchase or '없음'}\n"
            f"- 주 이용 플랫폼: {platform or '없음'}"
        )

        if keyword_history:
            kw_names = ", ".join(h["product_name"] for h in keyword_history if h.get("product_name"))
            if kw_names:
                prompt += f"\n- 관련 키워드 구매이력: {kw_names}"
            prompt += "\n\n위 키워드 관련 구매이력도 포함해 요약하세요."

        return _get_llm().invoke([HumanMessage(content=prompt)]).content.strip()
    except Exception:
        return preference.get("summary", "")


def _format_keyword_history_lines(keyword_history: list[dict[str, Any]]) -> str:
    """
    satisfaction/memo가 없는 레코드는 그 필드 자체를 생략한다 — "만족도: None"
    처럼 그대로 넣으면 LLM이 "명시적으로 정보 없음"과 "낮은 만족도"를 혼동할
    수 있다.
    """
    if not keyword_history:
        return "없음"
    lines = []
    for h in keyword_history:
        name = h.get("product_name") or "상품"
        detail = ""
        satisfaction = h.get("satisfaction")
        memo = h.get("memo")
        if satisfaction is not None or memo:
            parts = []
            if satisfaction is not None:
                parts.append(f"만족도:{satisfaction}")
            if memo:
                parts.append(f"메모:{memo}")
            detail = f" ({', '.join(parts)})"
        lines.append(f"- {name}{detail}")
    return "\n".join(lines)


def _classify_context(
    general_pref: dict[str, Any],
    keyword_history: list[dict[str, Any]],
    profile: Optional[dict[str, Any]],
    messages: Optional[list],
    keywords: list[str],
) -> ContextClassificationLLM:
    """
    이번 요청에 쓸 keyword_additions/exclude_additions/soft_preferences를
    한 번의 structured output 호출로 분류한다. safety_constraints는 여기
    관여하지 않는다 (프로필에서 코드로 직접 채움 — build_preference_context 참고).
    """
    try:
        profile_summary = "없음" if not profile else ", ".join(
            f"{k}:{v}" for k, v in profile.items() if v not in (None, [], "")
        ) or "없음"

        prompt = CONTEXT_CLASSIFICATION_PROMPT.format(
            profile_summary=profile_summary,
            general_preference_summary=general_pref.get("summary") or "없음",
            keyword_history_lines=_format_keyword_history_lines(keyword_history),
            session_text=_summarize_messages(messages or []) or "없음",
            current_keywords=", ".join(keywords) or "없음",
        )
        llm = _get_llm().with_structured_output(ContextClassificationLLM)
        result = llm.invoke([HumanMessage(content=prompt)])
        return result if isinstance(result, ContextClassificationLLM) else ContextClassificationLLM()
    except Exception as e:
        agent_logger.log(f"[context_agent] 분류 실패, 빈 분류로 대체: {e}")
        return ContextClassificationLLM()


def build_preference_context(
    user_id: str,
    keywords: list[str],
    messages: Optional[list] = None,
) -> dict[str, Any]:
    histories = _fetch_purchase_histories(user_id)
    if not histories:
        return {}

    # 일반 선호도: 캐시(mock 모드는 프로세스 메모리, real 모드는 DB) → 없으면 계산 + LLM 요약 저장
    general_pref = db_client.get_general_preference(user_id)
    cache_hit = general_pref is not None
    if cache_hit:
        agent_logger.log(f"[context_agent] 일반 선호도 캐시 HIT (user_id={user_id})")
    else:
        agent_logger.log("[context_agent] 일반 선호도 캐시 MISS → LLM 요약 생성 중...")
        general_pref = _compute_general_preference(histories)
        general_pref["summary"] = _generate_llm_summary(general_pref)
        db_client.save_general_preference(user_id, general_pref)
        agent_logger.log("[context_agent] 일반 선호도 캐시 저장 완료")

    # 장기 프로필 (알레르기/식이제약 등) — 스몰톡 에이전트가 채워넣는 값.
    # TTL 없음, 구매 완료로도 무효화되지 않음 (invalidate_purchase_derived_preferences 참고).
    profile = db_client.get_profile(user_id)

    # 키워드별 선호도 — satisfaction/memo도 함께 실어서 LLM이 직접 판단하게 한다
    # (별도 negative-feedback 집계 함수 없음, [:5] cap이 이미 크기를 제한함)
    keyword_history: list = []
    classification = ContextClassificationLLM()
    if keywords:
        keyword_history = [
            {
                "product_name": h.get("product_name"),
                "brand": h.get("brand"),
                "price": h.get("price_at_purchase"),
                "platform": h.get("platform"),
                "satisfaction": h.get("satisfaction"),
                "memo": h.get("memo"),
            }
            for h in histories
            if any(
                kw.lower() in (h.get("product_name") or "").lower()
                or kw.lower() in (h.get("keyword") or "").lower()
                or kw.lower() in (h.get("category") or "").lower()
                for kw in keywords
            )
        ][:5]

        if keyword_history:
            classification = _classify_context(
                general_pref, keyword_history, profile, messages, keywords,
            )

    # keyword_summary는 response_agent._format_preference가 소비하는 기존
    # 필드 — 별도 LLM 호출 없이 분류 결과에서 코드로 합성한다 (초안, 문구는
    # 추후 조정 예정).
    keyword_summary = ", ".join(classification.soft_preferences) if classification.soft_preferences else ""

    safety_constraints = list((profile or {}).get("allergens") or []) + list((profile or {}).get("diet_restrictions") or [])

    return {
        **general_pref,
        "keyword_history": keyword_history,
        "keyword_summary": keyword_summary,
        "_cache_hit": cache_hit,
        "keyword_additions": classification.keyword_additions,
        "exclude_additions": classification.exclude_additions,
        "soft_preferences": classification.soft_preferences,
        "safety_constraints": safety_constraints,
    }


def get_recommendation_context(
    user_id: str,
    keywords: list[str],
    intent: Optional[str] = None,
    messages: Optional[list] = None,
) -> dict[str, Any]:
    user_profile = _fetch_user_from_db(user_id) or {}
    default_address = _fetch_default_address_for_context(user_id)
    preference_memory = mock_get_preference_memory(user_id)

    histories = _fetch_purchase_histories(user_id)
    purchase_count = len(histories)

    query = " ".join(keywords)
    keyword_results = [
        h for h in histories
        if any(
            k.lower() in (h.get("product_name") or "").lower()
            or k.lower() in (h.get("keyword") or "").lower()
            or k.lower() in (h.get("category") or "").lower()
            for k in keywords
        )
    ][:5]

    use_personal_vector = purchase_count >= PERSONAL_VECTOR_THRESHOLD
    personal_vector_results = mock_vector_search_personal(user_id, query) if use_personal_vector else []

    age_group = user_profile.get("age_group")
    collective_vector_results = mock_vector_search_collective(query=query, age_group=age_group)

    retrieval_mode = "hybrid_personal_collective" if use_personal_vector else "keyword_collective"

    merged_context = _merge_recommendation_results(
        keyword_results=keyword_results,
        personal_vector_results=personal_vector_results,
        collective_vector_results=collective_vector_results,
        intent=intent,
    )

    preference_context = build_preference_context(user_id, keywords, messages)

    return {
        "user_profile": {
            "user_id": user_id,
            "name": user_profile.get("name"),
            "age_group": user_profile.get("age_group"),
            "default_address": default_address,
        },
        "preference_memory": preference_memory,
        "purchase_count": purchase_count,
        "retrieval_mode": retrieval_mode,
        "keyword_results": keyword_results,
        "personal_vector_results": personal_vector_results,
        "collective_vector_results": collective_vector_results,
        "merged_context": merged_context,
        "preference_context": preference_context,
    }


def _summarize_messages(messages: list) -> str:
    recent = messages[-5:] if len(messages) > 5 else messages
    parts = []
    for msg in recent:
        if isinstance(msg, dict):
            role, content = msg.get("role", ""), str(msg.get("content", ""))[:50]
        else:
            role = getattr(msg, "type", "") or getattr(msg, "role", "")
            content = str(getattr(msg, "content", ""))[:50]
        parts.append(f"[{role}] {content}")
    return " | ".join(parts)


def context_agent_node(state: ShoppingState, store: Optional[BaseStore] = None) -> dict:
    """
    Context Agent.

    [결제 완료 후] stage == "completed": 구매이력 저장 + 선호도 캐시 무효화 + 대화 요약.
    [Context Loading] buy/refine/compare_platforms: 프로필+선호도 컨텍스트 생성.
    """
    stage = state.get("stage")
    intent = state.get("intent")
    user_id = state.get("user_id", "")
    keywords = state.get("keywords") or []

    agent_logger.log(
        f"\n{'─'*40}\n[context_agent] 진입 | stage={stage}  intent={intent}  "
        f"user_id={user_id}  keywords={keywords}\n{'─'*40}"
    )

    updates: dict[str, Any] = {"last_agent": "context_agent"}

    if stage == "completed":
        # 구매이력 저장
        completed_purchase = state.get("completed_purchase")
        if completed_purchase and completed_purchase.get("order_id"):
            _save_purchase_history_from_completed(user_id, completed_purchase)
        else:
            agent_logger.log("[context_agent] completed_purchase 없음, 구매이력 저장 스킵")

        # 선호도 캐시 무효화
        _invalidate_preference_cache(user_id)

        # 대화 요약
        messages = state.get("messages") or []
        if len(messages) > 10:
            updates["conversation_summary"] = _summarize_messages(messages)

        agent_logger.log("[context_agent] 결제 완료 처리 완료")
        return updates

    recommendation_context = get_recommendation_context(
        user_id=user_id,
        keywords=keywords,
        intent=intent,
        messages=state.get("messages"),
    )

    pref_ctx = recommendation_context.get("preference_context") or {}
    agent_logger.log_context_agent(
        {
            "stage": stage,
            "intent": intent,
            "user_id": user_id,
            "keywords": keywords,
            "purchase_count": recommendation_context.get("purchase_count", 0),
            "retrieval_mode": recommendation_context.get("retrieval_mode"),
            "cache_hit": pref_ctx.get("_cache_hit", False),
        },
        {"preference_context": pref_ctx},
    )

    if store is not None:
        store.put(("recommendation_context", user_id), "latest", recommendation_context)

    # tier1(safety_constraints)/tier2(exclude_additions)는 검색 단계에서 바로
    # 걸러지도록 exclude_keywords에 병합. tier1은 keywords 쪽엔 넣지 않는다
    # (알레르기 성분명을 검색어로 쓰면 오히려 그 성분이 든 상품만 더 잡힘).
    existing_keywords = state.get("keywords") or []
    existing_exclude = state.get("exclude_keywords") or []
    merged_keywords = existing_keywords + [
        k for k in pref_ctx.get("keyword_additions", []) if k not in existing_keywords
    ]
    merged_exclude = existing_exclude + [
        k for k in (pref_ctx.get("exclude_additions", []) + pref_ctx.get("safety_constraints", []))
        if k not in existing_exclude
    ]

    return {
        **updates,
        "recommendation_context": recommendation_context,
        "keywords": merged_keywords,
        "exclude_keywords": merged_exclude,
    }


def get_recommendation_context_from_store(
    user_id: str,
    store: Optional[BaseStore] = None,
) -> dict[str, Any]:
    if store is None:
        return {}
    item = store.get(("recommendation_context", user_id), "latest")
    if item is None:
        return {}
    return item.value if hasattr(item, "value") else {}
