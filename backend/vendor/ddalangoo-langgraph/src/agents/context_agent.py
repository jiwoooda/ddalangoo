"""
Context Agent Node.

역할:
  [Context Loading]  buy/refine/compare_platforms → 사용자 프로필/구매이력/선호 조회
  [Post-Payment]     stage == "completed" → 구매이력 저장 + 선호도 캐시 무효화 + 대화 요약
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Optional
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.utils.agent_logger import agent_logger
from src.state.schema import ShoppingState
from src.state.node_inputs import ContextAgentInput, ContextAgentUpdate
from src.state.routed_signal import RoutedSignal
from src.state.smalltalk_schema import SMALLTALK_PROFILE_FIELDS, format_smalltalk_profile
from src.prompts.context_prompt import CONTEXT_CLASSIFICATION_PROMPT, SAFETY_SYNC_PROMPT
from src.tools import db_client
from src.utils.priority_resolver import resolve_precedence
from src.utils.retry import classify_failure, retry_call
from src.tools.mock_tools import (
    mock_get_preference_memory,
    mock_vector_search_personal,
    mock_vector_search_collective,
)

PERSONAL_VECTOR_THRESHOLD = 20


class RoutedSignalLLM(BaseModel):
    """LLM이 실제로 채우는 필드만. signal_id/timestamp는 코드가 나중에 붙인다."""
    value: str
    source: str  # RoutedSignal.SignalSource — Literal 강제는 ContextAgentOutput 파싱 시
    evidence: str
    decision_role: str  # RoutedSignal.DecisionRole


class ContextAgentOutput(BaseModel):
    """
    Context Agent 구조화 출력. safety_constraints(알레르기 등)는 여기 없다 —
    프로필에서 코드로 직접 채워서, LLM이 안전 정보를 중복/변형 생성하지
    않도록 한다 (새로 감지되는 안전 정보는 SAFETY_SYNC_PROMPT가 별도 처리).
    """
    routed_signals: list[RoutedSignalLLM] = Field(default_factory=list)


class SafetySignalUpdate(BaseModel):
    """세션 발화에서 새로 감지된 안전 정보. 감지 안 되면 둘 다 빈 리스트."""
    new_allergens: list[str] = Field(default_factory=list)
    new_diet_restrictions: list[str] = Field(default_factory=list)


_SAFETY_TRIGGER_KEYWORDS = (
    "알레르기", "알러지", "못먹", "안먹", "불내증", "제한식", "알레르겐", "먹으면 안",
)

_context_llm = None


def _get_llm():
    global _context_llm
    if _context_llm is None:
        try:
            from configs.llm_config import get_llm
            # retry_owner="application": 호출부(_sync_safety_from_session/
            # _classify_context)가 retry_call()로 감싸므로 SDK 자체 재시도는 끈다.
            _context_llm = get_llm("context", temperature=0, max_tokens=400, retry_owner="application")
        except Exception:
            from langchain_anthropic import ChatAnthropic
            _context_llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0, max_tokens=400, max_retries=0)
    return _context_llm


# ── I: 세션 안전정보 동기 반영 ────────────────────────────────────────
# 다른 선호 정보(브랜드, 가격대 등)와 달리, 이번 세션에서 "처음" 언급된
# 알레르기/식이제약은 이번 요청 처리 전에 profile에 즉시 반영돼야 한다.
# 그렇지 않으면 방금 말한 알레르기가 이번 추천에 전혀 반영되지 않는다
# (safety_constraints는 profile에서만 읽고, LLM 분류 대상이 아니기 때문).

def _detect_safety_trigger(messages: Optional[list]) -> bool:
    text = _summarize_messages(messages or [])
    return any(kw in text for kw in _SAFETY_TRIGGER_KEYWORDS)


def _sync_safety_from_session(
    user_id: str,
    profile: Optional[dict[str, Any]],
    messages: Optional[list],
) -> dict[str, Any]:
    """
    세션 발화에 안전 관련 키워드가 감지될 때만(경량 트리거) LLM으로 추출해
    profile에 동기적으로 merge 저장한다. 트리거가 없으면 LLM 호출 없이
    프로필을 그대로 반환한다 — 매 요청마다 콜을 늘리지 않기 위함.
    """
    if not _detect_safety_trigger(messages):
        return profile or {}

    session_text = _summarize_messages(messages or [])
    try:
        structured = _get_llm().with_structured_output(SafetySignalUpdate, method="json_schema")
        result = retry_call(
            structured.invoke, [HumanMessage(content=SAFETY_SYNC_PROMPT.format(session_text=session_text))]
        )
        if not isinstance(result, SafetySignalUpdate):
            return profile or {}
    except Exception as e:
        agent_logger.log(f"[context_agent] 안전정보 동기화 실패({classify_failure(e).value}): {e}")
        return profile or {}

    if not result.new_allergens and not result.new_diet_restrictions:
        return profile or {}

    merged = dict(profile or {})
    merged["allergens"] = db_client.merge_list_field((profile or {}).get("allergens"), result.new_allergens)
    merged["diet_restrictions"] = db_client.merge_list_field(
        (profile or {}).get("diet_restrictions"), result.new_diet_restrictions
    )
    db_client.save_profile(user_id, merged)
    agent_logger.log(
        f"[context_agent] 세션에서 안전정보 감지 → profile 즉시 갱신 "
        f"allergens+={result.new_allergens} diet+={result.new_diet_restrictions}"
    )
    return merged


# ── DB 접근은 전부 db_client(mock/real 모드 전환)를 경유한다 ────────────

def _fetch_purchase_histories(user_id: str) -> list[dict[str, Any]]:
    result = db_client.get_purchase_histories(user_id)
    agent_logger.log(f"[context_agent] 구매이력 로드: {len(result)}건 (user_id={user_id})")
    return result


def _fetch_user_from_db(user_id: str) -> dict[str, Any] | None:
    return db_client.get_user(user_id)


def _fetch_default_address_for_context(user_id: str) -> dict[str, Any] | None:
    return db_client.get_default_address(user_id)


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


def _to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _purchase_history_timestamp(keyword_history: list[dict[str, Any]]) -> Optional[str]:
    """
    RoutedSignal.evidence는 자유 텍스트라 특정 구매이력 레코드에 정확히
    매핑할 수 없다 — keyword_history는 이미 최신순 정렬돼 들어오므로
    (mock_get_purchase_history/get_histories_by_user_id_db 둘 다 최신순),
    첫 번째 항목의 purchased_at을 이 호출의 purchase_history 신호 전체의
    대표 시각으로 쓴다 (근사치).
    """
    for h in keyword_history:
        ts = _to_iso(h.get("purchased_at"))
        if ts:
            return ts
    return None


def _enrich_signals(
    llm_signals: list[RoutedSignalLLM],
    keyword_history: list[dict[str, Any]],
    profile: Optional[dict[str, Any]],
) -> list[RoutedSignal]:
    """
    signal_id/timestamp는 LLM이 추측하지 않고 코드가 채운다.

    timestamp는 purchase_history 소스만 채운다 (실제 구매일 purchased_at —
    "예전엔 프리미엄만, 최근엔 최저가"처럼 진짜 시간 비교가 의미 있는
    유일한 케이스). general_context/session_smalltalk는 None으로 둔다:
    - general_context vs session_smalltalk 충돌은 Priority Resolver의
      카테고리 규칙(session이 항상 우선)으로 이미 해결되어 timestamp가
      불필요하다.
    - session_smalltalk끼리의 충돌은 routed_signals 리스트 순서(=발화
      등장 순서, CONTEXT_CLASSIFICATION_PROMPT가 이 순서 유지를 지시함)로
      판단한다 (priority_resolver.rank_by_recency 참고).
    이전엔 general_context에 profile의 computed_at을 썼었는데, 그 필드가
    안전정보 갱신 등 무관한 쓰기에도 같이 갱신돼서 recency 판단이 왜곡될
    수 있는 결함이 있어 제거했다.
    """
    purchase_ts = _purchase_history_timestamp(keyword_history)

    enriched: list[RoutedSignal] = []
    for i, sig in enumerate(llm_signals):
        source = sig.source if sig.source in ("general_context", "purchase_history", "session_smalltalk") else "session_smalltalk"
        decision_role = sig.decision_role if sig.decision_role in ("retrieval", "explicit_exclusion", "soft_preference") else "soft_preference"
        timestamp = purchase_ts if source == "purchase_history" else None
        enriched.append(RoutedSignal(
            signal_id=f"sig_{i}",
            value=sig.value,
            source=source,
            evidence=sig.evidence,
            decision_role=decision_role,
            timestamp=timestamp,
        ))
    return enriched


def _classify_context(
    general_pref: dict[str, Any],
    keyword_history: list[dict[str, Any]],
    profile: Optional[dict[str, Any]],
    messages: Optional[list],
    keywords: list[str],
) -> list[RoutedSignal]:
    """
    이번 요청에 쓸 신호를 routed_signals로 한 번의 structured output 호출로
    분류한다. safety_constraints는 여기 관여하지 않는다 (프로필에서 코드로
    직접 채움 — build_preference_context 참고).
    """
    try:
        profile_summary = "없음" if not profile else ", ".join(
            f"{k}:{v}" for k, v in profile.items()
            if v not in (None, [], "") and k != "computed_at" and k not in SMALLTALK_PROFILE_FIELDS
        ) or "없음"

        prompt = CONTEXT_CLASSIFICATION_PROMPT.format(
            profile_summary=profile_summary,
            smalltalk_profile_summary=format_smalltalk_profile(profile),
            general_preference_summary=general_pref.get("summary") or "없음",
            keyword_history_lines=_format_keyword_history_lines(keyword_history),
            session_text=_summarize_messages(messages or []) or "없음",
            current_keywords=", ".join(keywords) or "없음",
        )
        structured = _get_llm().with_structured_output(ContextAgentOutput, method="json_schema")
        result = retry_call(structured.invoke, [HumanMessage(content=prompt)])
        if not isinstance(result, ContextAgentOutput):
            return []
        return _enrich_signals(result.routed_signals, keyword_history, profile)
    except Exception as e:
        agent_logger.log(f"[context_agent] 분류 실패({classify_failure(e).value}), 빈 분류로 대체: {e}")
        return []


def build_preference_context(
    user_id: str,
    keywords: list[str],
    messages: Optional[list] = None,
) -> dict[str, Any]:
    # 장기 프로필(알레르기 등) — 구매이력 유무와 무관하게 항상 먼저 조회한다.
    # 예전엔 구매이력이 없으면 함수 전체가 빈 dict를 반환해서, 구매이력 없는
    # 신규 유저가 세션에서 알레르기를 처음 말해도 이번 요청에 전혀 반영이
    # 안 되는 안전 문제가 있었다 — 그래서 profile/safety는 아래 히스토리
    # 존재 여부 체크보다 먼저 처리한다.
    profile = db_client.get_profile(user_id)
    profile = _sync_safety_from_session(user_id, profile, messages)
    safety_constraints = list((profile or {}).get("allergens") or []) + list((profile or {}).get("diet_restrictions") or [])
    smalltalk_profile_summary = format_smalltalk_profile(profile)
    has_smalltalk_signals = smalltalk_profile_summary != "없음"

    histories = _fetch_purchase_histories(user_id)

    # 일반 선호도: 구매이력이 있을 때만 계산 — 캐시(mock 모드는 프로세스
    # 메모리, real 모드는 DB) → 없으면 계산 + LLM 요약 저장
    general_pref: dict[str, Any] = {}
    cache_hit = False
    if histories:
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

    # 키워드별 선호도 — satisfaction/memo도 함께 실어서 LLM이 직접 판단하게 한다
    # (별도 negative-feedback 집계 함수 없음, [:5] cap이 이미 크기를 제한함)
    keyword_history: list = []
    if keywords and histories:
        keyword_history = [
            {
                "product_name": h.get("product_name"),
                "brand": h.get("brand"),
                "price": h.get("price_at_purchase"),
                "platform": h.get("platform"),
                "satisfaction": h.get("satisfaction"),
                "memo": h.get("memo"),
                "purchased_at": h.get("purchased_at"),
            }
            for h in histories
            if any(
                kw.lower() in (h.get("product_name") or "").lower()
                or kw.lower() in (h.get("keyword") or "").lower()
                or kw.lower() in (h.get("category") or "").lower()
                for kw in keywords
            )
        ][:5]

    # 구매이력 keyword 매치가 있거나, smalltalk_agent가 수집한 신호가 있으면
    # 분류한다. 구매이력이 아예 없는 신규유저도 smalltalk 신호만으로 분류
    # 대상이 되어야 한다 — 예전엔 histories가 없으면 함수 전체가 조기
    # 반환해서, 신규유저의 잡담 신호가 tier 분류 기회 자체가 없었다
    # (context_routing_eval 스팟체크로 확인된 문제).
    routed_signals: list[RoutedSignal] = []
    if keyword_history or has_smalltalk_signals:
        routed_signals = _classify_context(
            general_pref, keyword_history, profile, messages, keywords,
        )

    # Priority Resolver: 이번 Intent(keywords)가 과거 explicit_exclusion과
    # 같은 대상을 다시 명시하면 그 배제를 무효화한다. safety는 여기 관여
    # 안 함 (위에서 이미 profile 기준으로 확정).
    resolved = resolve_precedence(keywords, routed_signals)
    keyword_additions = [s.value for s in resolved["retrieval_signals"]]
    exclude_additions = [s.value for s in resolved["effective_exclusions"]]
    soft_preference_signals = resolved["active_soft_preferences"]

    if resolved["overridden_exclusions"]:
        agent_logger.log(
            "[context_agent] Priority Resolver: 이번 Intent가 명시적으로 재요청해서 배제 무효화 → "
            + ", ".join(s.value for s in resolved["overridden_exclusions"])
        )

    # keyword_summary는 response_agent._format_preference가 소비하는 기존
    # 필드 — 별도 LLM 호출 없이 분류 결과에서 코드로 합성한다 (초안, 문구는
    # 추후 조정 예정).
    keyword_summary = ", ".join(s.value for s in soft_preference_signals) if soft_preference_signals else ""

    return {
        **general_pref,
        "keyword_history": keyword_history,
        "keyword_summary": keyword_summary,
        "_cache_hit": cache_hit,
        "keyword_additions": keyword_additions,
        "exclude_additions": exclude_additions,
        "soft_preferences": [s.model_dump() for s in soft_preference_signals],
        "safety_constraints": safety_constraints,
        "overridden_exclusions": [s.model_dump() for s in resolved["overridden_exclusions"]],
    }


def _build_local_recommendation_context(
    user_id: str,
    keywords: list[str],
    intent: Optional[str],
) -> dict[str, Any]:
    """
    get_recommendation_context 중 build_preference_context(Stage0, LLM콜 있음)와
    무관한 부분만 떼어낸 것 — user_profile/구매이력/벡터검색은 서로만 의존하고
    preference_context 쪽 결과를 전혀 안 쓴다. 아래 get_recommendation_context가
    이 함수와 build_preference_context를 스레드로 동시에 돌린다.
    """
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
    }


def get_recommendation_context(
    user_id: str,
    keywords: list[str],
    intent: Optional[str] = None,
    messages: Optional[list] = None,
) -> dict[str, Any]:
    # _build_local_recommendation_context(DB/mock 조회 위주, 빠름)와
    # build_preference_context(Stage0 LLM콜 포함, 느림)는 서로 결과를
    # 안 쓰는 독립 브랜치라 스레드로 동시에 돌린다 — LLM 콜이 훨씬 오래
    # 걸리므로 로컬 브랜치의 지연시간은 사실상 겹쳐서 사라진다.
    # (안전정보 동기화→분류 순서 의존성은 build_preference_context 내부에서
    # 이미 순차로 지켜지고 있고, 이 병렬화와는 무관하다.)
    with ThreadPoolExecutor(max_workers=2) as executor:
        local_future = executor.submit(_build_local_recommendation_context, user_id, keywords, intent)
        preference_future = executor.submit(build_preference_context, user_id, keywords, messages)
        local_context = local_future.result()
        preference_context = preference_future.result()

    return {
        **local_context,
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


def context_agent_node(state: ContextAgentInput) -> ContextAgentUpdate:
    """
    Context Agent.

    [결제 완료 후] stage == "completed": 구매이력 저장 + 선호도 캐시 무효화 + 대화 요약.
    [Context Loading] buy/refine/compare_platforms: 프로필+선호도 컨텍스트 생성.

    recommendation_context는 ShoppingState가 유일한 source of truth다 — 이전엔
    Store에도 같은 값을 write했었는데, 그걸 읽는 코드가 어디에도 없어서 순수
    낭비였다(get_recommendation_context_from_store가 아무 데서도 호출되지
    않음). 세션 간 재사용이 실제로 필요해지면 그때 다시 연결한다.
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
        # 구매이력 저장은 payment_agent_node → mock_place_order →
        # mock_save_purchase_history 경로로 이미 결제 시점에 이루어진다.
        # 여기서 별도로 할 일 없음 — 예전엔 state["completed_purchase"]를
        # 읽어서 다시 저장하려 했는데, 그 필드가 애초에 어디서도 write되지
        # 않아 항상 스킵되는 죽은 코드였다(제거함).

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
