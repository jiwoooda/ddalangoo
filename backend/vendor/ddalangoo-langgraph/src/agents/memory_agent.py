"""
Memory Agent Node.

역할:
  [Context Loading]  사용자 프로필/구매 이력/선호 조회 → recommendation_context 생성 → store 저장.
  [Tool Dispatch]    tool_calls를 State에 올려 backend가 실행하도록 위임.

호출 시점:
  - router → memory_agent (reorder intent)          : context loading + search tool
  - payment_agent → memory_agent (결제 완료 후)     : conversation summary tool only
"""
import re
from typing import Any, Optional
from langgraph.store.base import BaseStore

from src.state.schema import ShoppingState, MemoryState, bridge_memory_to_shopping
from src.utils.agent_logger import agent_logger
from src.tools.mock_tools import (
    mock_get_user,
    mock_get_default_address,
    mock_get_preference_memory,
    mock_count_purchases,
    mock_keyword_search_history,
    mock_vector_search_personal,
    mock_vector_search_collective,
)

PERSONAL_VECTOR_THRESHOLD = 20


def _get_latest_user_text(state: ShoppingState) -> str:
    messages = state.get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, dict):
            content = msg.get("content")
            role = msg.get("role") or msg.get("type")
            if content and role in (None, "user", "human"):
                return str(content)
        else:
            content = getattr(msg, "content", None)
            msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
            if content and msg_type in (None, "human", "user"):
                return str(content)
    return ""


def _candidate_to_search_result(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_name": candidate.get("product_name", ""),
        "price": candidate.get("price_at_purchase", 0),
        "rating": None,
        "review_count": None,
        "delivery": None,
        "delivery_fee": None,
        "platform": candidate.get("platform", ""),
        "image_url": None,
        "product_url": candidate.get("product_url", ""),
        "option_text": candidate.get("option_text"),
        "selected_options": candidate.get("selected_options") or {},
        "product_id": candidate.get("product_id"),
        "product_option_id": candidate.get("product_option_id"),
        "purchase_history_id": candidate.get("purchase_history_id"),
        "score": candidate.get("score"),
        "is_sold_out": False,
        "raw": candidate,
    }


def _fallback_resolve_reorder_memory(
    user_id: str,
    query: str,
    keywords: list[str],
    top_k: int = 5,
) -> dict[str, Any]:
    history = mock_keyword_search_history(user_id, keywords or [query], limit=top_k)
    candidates = []
    for item in history:
        candidates.append({
            "purchase_history_id": item.get("id"),
            "product_id": item.get("product_id"),
            "product_option_id": item.get("product_option_id"),
            "product_name": item.get("product_name"),
            "product_url": item.get("product_url"),
            "option_text": item.get("option_text"),
            "selected_options": item.get("selected_options") or {},
            "price_at_purchase": item.get("price_at_purchase", 0),
            "platform": item.get("platform"),
            "purchased_at": item.get("purchased_at"),
            "score": 0.8,
            "reason": "mock keyword match",
        })

    if not candidates:
        return {
            "resolution_type": "no_match",
            "resolved": False,
            "needs_user_selection": False,
            "selected_candidate": None,
            "candidates": [],
        }

    # 여러 개면 가장 최근 구매를 선택 (purchased_at 내림차순)
    candidates.sort(key=lambda c: c.get("purchased_at") or "", reverse=True)
    return {
        "resolution_type": "resolved",
        "resolved": True,
        "needs_user_selection": False,
        "selected_candidate": candidates[0],
        "candidates": candidates,
    }


def _resolve_reorder_memory(
    user_id: str,
    query: str,
    keywords: list[str],
    top_k: int = 5,
) -> dict[str, Any]:
    try:
        from app.services.memory_tools import resolve_reorder_memory

        return resolve_reorder_memory(
            user_id=int(user_id),
            query=query,
            keywords=keywords,
            top_k=top_k,
        )
    except Exception:
        return _fallback_resolve_reorder_memory(user_id, query, keywords, top_k)


def _merge_recommendation_results(
    keyword_results: list[dict[str, Any]],
    personal_vector_results: list[dict[str, Any]],
    collective_vector_results: list[dict[str, Any]],
    intent: Optional[str] = None,
) -> list[dict[str, Any]]:
    merged = []
    seen: set = set()

    if intent == "reorder":
        sources = [
            ("keyword", keyword_results),
            ("personal_vector", personal_vector_results),
            ("collective_vector", collective_vector_results),
        ]
    else:
        sources = [
            ("personal_vector", personal_vector_results),
            ("keyword", keyword_results),
            ("collective_vector", collective_vector_results),
        ]

    for source, results in sources:
        for item in results:
            key = (
                item.get("product_url")
                or item.get("product_name")
                or item.get("id")
            )
            if not key or key in seen:
                continue
            item = dict(item)
            item["_memory_source"] = source
            merged.append(item)
            seen.add(key)

    return merged[:10]


def _run_async_with_fresh_engine(coro_factory) -> Any:
    """
    sync 컨텍스트에서 async DB 작업 실행.
    매 호출마다 엔진을 새로 생성하고 dispose() — asyncpg 풀이 이전 루프에
    묶이는 'Event loop is closed' 오류를 방지한다.
    """
    import asyncio
    import os as _os

    _backend = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../../../../"))
    import sys as _sys
    if _backend not in _sys.path:
        _sys.path.insert(0, _backend)

    async def _runner():
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        database_url = _os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL not set")
        engine = create_async_engine(database_url, pool_pre_ping=True, pool_size=1, max_overflow=0)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
        try:
            async with factory() as session:
                return await coro_factory(session)
        finally:
            await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_runner())
    finally:
        loop.close()


def _fetch_purchase_histories(user_id: str) -> list[dict[str, Any]]:
    """구매이력 조회. DB 우선, 실패 시 mock JSON fallback."""
    import os
    import sys

    _backend = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
    if _backend not in sys.path:
        sys.path.insert(0, _backend)

    async def _from_db(session):
        from app.repositories.purchase_history_repository import get_histories_by_user_id_db
        return await get_histories_by_user_id_db(session, int(user_id))

    try:
        result = _run_async_with_fresh_engine(_from_db)
        agent_logger.log(f"[memory_agent] DB 구매이력 로드: {len(result)}건 (user_id={user_id})")
        return result
    except Exception as e:
        agent_logger.log(f"[memory_agent] DB 조회 실패, mock fallback 시도: {e}")

    # fallback: mock JSON
    try:
        from app.repositories import purchase_history_repository
        result = purchase_history_repository.get_histories_by_user_id(int(user_id))
        agent_logger.log(f"[memory_agent] mock JSON 구매이력: {len(result)}건 (user_id={user_id})")
        return result
    except Exception:
        agent_logger.log(f"[memory_agent] 구매이력 로드 완전 실패 → 빈 리스트 반환")
        return []


def _compute_general_preference(histories: list[dict[str, Any]]) -> dict[str, Any]:
    """전체 구매이력에서 일반 선호도를 계산한다."""
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
        price_range = {
            "avg": sum(prices) // len(prices),
            "min": min(prices),
            "max": max(prices),
        }

    repurchase_patterns = [
        name
        for name, count in sorted(product_counts.items(), key=lambda x: -x[1])
        if count >= 2
    ][:5]

    preferred_platform = (
        max(platform_counts, key=platform_counts.get) if platform_counts else None
    )

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
    """구매이력 통계에서 자연어 선호도 요약을 LLM으로 생성한다. 실패 시 빈 문자열 반환."""
    try:
        import anthropic
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

        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        return ""


def build_preference_context(
    user_id: str,
    keywords: list[str],
) -> dict[str, Any]:
    """
    구매이력 기반 선호도 요약 생성.

    [일반 선호도] 전체 구매이력 기반 — JSON 파일에 캐시 (TTL 24h).
                  재시작 후에도 유지. 구매 완료 시 invalidate.
    [키워드 선호도] 요청 키워드와 매칭되는 이력만 — 매번 fresh 계산.

    product_agent 프롬프트에 주입해 개인화 랭킹에 활용한다.
    """
    histories = _fetch_purchase_histories(user_id)
    if not histories:
        return {}

    # ── 일반 선호도: 캐시 조회 → 없으면 계산 + LLM 요약 후 저장 ──
    cache_hit = False
    try:
        from app.repositories import user_preference_repository
        general_pref = user_preference_repository.get_general_preference(int(user_id))
        if general_pref:
            cache_hit = True
            agent_logger.log(f"[memory_agent] 일반 선호도 캐시 HIT (user_id={user_id})")
        else:
            agent_logger.log(f"[memory_agent] 일반 선호도 캐시 MISS → LLM 요약 생성 중...")
            general_pref = _compute_general_preference(histories)
            general_pref["summary"] = _generate_llm_summary(general_pref)
            user_preference_repository.save_general_preference(int(user_id), general_pref)
            agent_logger.log(f"[memory_agent] 일반 선호도 캐시 저장 완료")
    except Exception as e:
        agent_logger.log(f"[memory_agent] 선호도 캐시 예외 → 직접 계산: {e}")
        general_pref = _compute_general_preference(histories)
        general_pref["summary"] = _generate_llm_summary(general_pref)

    summary_snippet = (general_pref.get("summary") or "")[:100]
    agent_logger.log(f"[memory_agent] 일반 선호도 요약: {summary_snippet}")

    # ── 키워드별 선호도: 매 요청마다 계산 (키워드가 달라지므로 캐시 없음) ──
    keyword_history: list = []
    keyword_summary: str = ""
    if keywords:
        try:
            from app.repositories import user_preference_repository
            cached_keyword_history = user_preference_repository.get_keyword_preference(
                int(user_id),
                keywords,
            )
        except Exception as e:
            agent_logger.log(f"[memory_agent] 키워드 선호도 캐시 예외 → 직접 계산: {e}")
            cached_keyword_history = None

        if cached_keyword_history is not None:
            keyword_history = cached_keyword_history
            agent_logger.log(f"[memory_agent] 키워드 선호도 캐시 HIT (user_id={user_id}, keywords={keywords})")
        else:
            keyword_history = [
                {
                    "product_name": h.get("product_name"),
                    "brand": h.get("brand"),
                    "price": h.get("price_at_purchase"),
                    "platform": h.get("platform"),
                }
                for h in histories
                if any(kw.lower() in (h.get("product_name") or "").lower() for kw in keywords)
            ][:5]
            try:
                from app.repositories import user_preference_repository
                user_preference_repository.save_keyword_preference(
                    int(user_id),
                    keywords,
                    keyword_history,
                )
            except Exception as e:
                agent_logger.log(f"[memory_agent] 키워드 선호도 캐시 저장 실패: {e}")

        agent_logger.log(
            f"[memory_agent] 키워드 '{keywords}' 매칭 이력: {len(keyword_history)}건"
            + (f" → {[h['product_name'] for h in keyword_history]}" if keyword_history else "")
        )
        if keyword_history:
            agent_logger.log(f"[memory_agent] 키워드 선호도 요약 생성 중...")
            keyword_summary = _generate_llm_summary(general_pref, keyword_history)
            agent_logger.log(f"[memory_agent] 키워드 선호도 요약: {keyword_summary[:100]}")

    return {
        **general_pref,
        "keyword_history": keyword_history,
        "keyword_summary": keyword_summary,
        "_cache_hit": cache_hit,
    }


def get_recommendation_context(
    user_id: str,
    keywords: list[str],
    intent: Optional[str] = None,
) -> dict[str, Any]:
    """
    추천용 Retrieval Context 생성.
    - reorder: keyword 우선
    - 구매 20개 미만: keyword + collective vector
    - 구매 20개 이상: keyword + personal vector + collective vector
    """
    user_profile = mock_get_user(user_id) or {}
    default_address = mock_get_default_address(user_id)
    preference_memory = mock_get_preference_memory(user_id)
    purchase_count = mock_count_purchases(user_id)

    query = " ".join(keywords)
    keyword_results = mock_keyword_search_history(user_id, keywords)

    use_personal_vector = purchase_count >= PERSONAL_VECTOR_THRESHOLD
    personal_vector_results = (
        mock_vector_search_personal(user_id, query) if use_personal_vector else []
    )

    age_group = user_profile.get("age_group")
    collective_vector_results = mock_vector_search_collective(
        query=query, age_group=age_group
    )

    if use_personal_vector:
        retrieval_mode = "hybrid_personal_collective"
    elif intent == "reorder":
        retrieval_mode = "keyword_only"
    else:
        retrieval_mode = "keyword_collective"

    merged_context = _merge_recommendation_results(
        keyword_results=keyword_results,
        personal_vector_results=personal_vector_results,
        collective_vector_results=collective_vector_results,
        intent=intent,
    )

    preference_context = build_preference_context(user_id, keywords)

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
    """메시지 요약 (임시: 최근 5개 단순 연결 / TODO: Claude API로 교체)."""
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


def _extract_reorder_keyword(user_input: str, keywords: list[str]) -> str:
    """재구매 키워드 추출: state keywords 우선, 없으면 간단 패턴 매칭."""
    if keywords:
        return " ".join(keywords)
    for pattern in [r"저번에\s*산\s*(\S+)", r"(\S+)\s*다시", r"(\S+)\s*또"]:
        m = re.search(pattern, user_input)
        if m:
            return m.group(1)
    return user_input


def _build_tool_calls(state: ShoppingState) -> list[dict[str, Any]]:
    """State를 보고 필요한 tool_calls 목록을 생성한다."""
    calls: list[dict[str, Any]] = []
    intent = state.get("intent")
    messages = state.get("messages") or []

    # 1. 메시지 수 초과 → 대화 요약 저장
    if len(messages) > 10:
        summary = _summarize_messages(messages)
        calls.append({
            "tool": "save_conversation_summary",
            "args": {
                "conversation_id": state.get("conversation_id"),
                "summary": summary,
                "message_count": len(messages),
            },
        })

    return calls


def _save_purchase_history(state: ShoppingState) -> None:
    """결제 완료 후 구매이력을 DB에 저장한다. 실패 시 조용히 무시.

    FastAPI 경유 시: state["order"]["orderId"] 존재 → create_histories_from_order_db (order/payment 연결)
    main.py 직접 실행 시: order 없음 → save_purchase_history_from_state_db (state에서 직접 저장)
    """
    user_id = state.get("user_id", "")
    order_info = state.get("order") or {}
    payment_info = state.get("payment") or {}
    order_id = order_info.get("orderId")
    payment_id = payment_info.get("paymentId")

    async def _write_with_order(session):
        from app.repositories.purchase_history_repository import create_histories_from_order_db
        await create_histories_from_order_db(session, order_id=order_id, payment_id=payment_id)

    async def _write_from_state(session):
        product = state.get("selected_product") or {}
        if not product:
            return
        quantity = state.get("quantity") or 1
        keywords = state.get("keywords") or []
        keyword = keywords[0] if keywords else None
        from app.repositories.purchase_history_repository import save_purchase_history_from_state_db
        await save_purchase_history_from_state_db(
            session,
            user_id=int(user_id),
            product=product,
            quantity=quantity,
            keyword=keyword,
        )

    try:
        _run_async_with_fresh_engine(_write_with_order if order_id else _write_from_state)
        path = "order_id 연결" if order_id else "state 직접"
        agent_logger.log(f"[memory_agent] 구매이력 저장 완료 ({path}, user_id={user_id})")
    except Exception as e:
        agent_logger.log(f"[memory_agent] 구매이력 저장 실패: {e}")
        print(f"[memory_agent] 구매이력 저장 실패: {e}")


def memory_agent_node(state: ShoppingState, store: Optional[BaseStore] = None) -> dict:
    """
    Memory Agent.

    [결제 완료 후] stage=="completed": tool_calls만 방출하고 종료.
    [reorder 탐색] intent=="reorder":  context loading + tool_calls 방출.
    """
    stage = state.get("stage")
    intent = state.get("intent")
    user_id = state.get("user_id", "")
    keywords = state.get("keywords") or []

    agent_logger.log(
        f"\n{'─'*40}\n[memory_agent] 진입 | stage={stage}  intent={intent}  "
        f"user_id={user_id}  keywords={keywords}\n{'─'*40}"
    )

    tool_calls = _build_tool_calls(state)
    updates: dict[str, Any] = {"last_agent": "memory_agent", "tool_calls": tool_calls or None}

    # 메시지 요약이 생성됐다면 state에도 기록
    if len(state.get("messages") or []) > 10:
        updates["conversation_summary"] = _summarize_messages(state.get("messages") or [])

    # ── 결제 완료 후 호출: 구매이력 저장 (선호도 캐시는 TTL로 자연 만료) ──
    if stage == "completed":
        agent_logger.log(f"[memory_agent] 결제 완료 → 구매이력 저장 시작")
        _save_purchase_history(state)
        return updates

    # ── reorder: 선호도 컨텍스트 불필요 — resolver만 실행 ──
    if intent == "reorder":
        query = _get_latest_user_text(state) or _extract_reorder_keyword("", keywords)
        agent_logger.log(f"[memory_agent] reorder → resolver 직행 (query='{query}', keywords={keywords})")
        resolver_result = _resolve_reorder_memory(
            user_id=user_id,
            query=query,
            keywords=keywords,
            top_k=5,
        )
        agent_logger.log(f"[memory_agent] resolver 결과: {resolver_result.get('resolution_type')}  "
                         f"selected={resolver_result.get('selected_candidate', {}).get('product_name') if resolver_result.get('selected_candidate') else None}")
        search_results = [
            _candidate_to_search_result(candidate)
            for candidate in (resolver_result.get("candidates") or [])
        ]
        return {
            **bridge_memory_to_shopping({}),
            "reorder_resolution": resolver_result,
            "search_results": search_results,
            "stage": "searching",
            "selected_product": None,
            "product_url": None,
            "current_product_index": 0,
            "explanation": None,
            "highlight_specs": [],
            "scored_products": [],
            "recommended_products": [],
            **updates,
        }

    # ── Context Loading (buy / refine / 기타) ──
    recommendation_context = get_recommendation_context(
        user_id=user_id,
        keywords=keywords,
        intent=intent,
    )

    pref_ctx = recommendation_context.get("preference_context") or {}
    agent_logger.log_memory_agent(
        {
            "stage": stage,
            "intent": intent,
            "user_id": user_id,
            "keywords": keywords,
            "cache_hit": pref_ctx.get("_cache_hit", False),
        },
        {"preference_context": pref_ctx},
    )
    agent_logger.log(
        f"[memory_agent] → platform_agent로 넘길 preference_context: "
        f"요약길이={len(pref_ctx.get('summary') or '')}자  "
        f"키워드요약길이={len(pref_ctx.get('keyword_summary') or '')}자"
    )

    if store is not None:
        store.put(
            ("recommendation_context", user_id),
            "latest",
            recommendation_context,
        )

    return {
        **bridge_memory_to_shopping({}),
        "recommendation_context": recommendation_context,
        **updates,
    }


def get_recommendation_context_from_store(
    user_id: str,
    store: Optional[BaseStore] = None,
) -> dict[str, Any]:
    """Store에서 recommendation_context 조회."""
    if store is None:
        return {}
    item = store.get(("recommendation_context", user_id), "latest")
    if item is None:
        return {}
    return item.value if hasattr(item, "value") else {}
