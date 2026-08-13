"""
Product Agent Node.

역할: 멀티플랫폼 검색(tool) + 랭킹.
- naver/coupang/kurly 동시 검색 → 후보군 수집
- rank_products tool 호출 → 순위화
- 설명 생성은 Response Agent에서 담당

next/deny 재호출 시 검색 스킵 — 기존 recommended_products 재사용.
"""
import json
import re
from typing import Any, Literal
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from configs.llm_config import get_llm

from src.state.schema import ShoppingState
from src.state.node_inputs import ProductAgentInput, ProductAgentUpdate
from src.tools.mock_search import search_products
from src.prompts.scoring_prompt import SCORING_PROMPT
from src.utils.agent_logger import agent_logger
from src.utils.aggregator import aggregate, normalize_fixed_axes, normalize_weights
from src.utils.retry import classify_failure, retry_call

ALL_PLATFORMS = ["naver", "coupang", "kurly"]


def _no_results_message(keywords: list[str]) -> str:
    label = keywords[0] if keywords else None
    if label:
        return f"{label}를 찾지 못했어요. 다른 상품을 말씀해 주세요."
    return "찾으시는 상품이 없어요. 다른 상품을 말씀해 주세요."


def _missing_product_message(keywords: list[str]) -> str:
    return _no_results_message(keywords)


def _no_more_products_message(keywords: list[str]) -> str:
    label = keywords[0] if keywords else None
    if label:
        return f"{label}로는 더 추천할 상품이 없어요. 다른 상품을 찾아볼까요?"
    return "더 추천할 상품이 없어요. 다른 상품을 찾아볼까요?"

CONDITION_MAP = {
    "최저가": "price_asc",
    "가성비": "value",
    "빠른배송": "delivery_fast",
    "인기순": "popularity",
    "리뷰좋은": "review_score",
    "무료배송": "free_shipping",
}

# 평균 구매가 기반 condition 추론 테이블 (threshold 이하이면 해당 condition 적용)
_AVG_PRICE_CONDITION: list[tuple[int, str]] = [
    (12_000, "최저가"),
    (40_000, "가성비"),
]


def _derive_search_params(
    condition: str | None,
    preference_context: dict[str, Any],
) -> tuple[str | None, str | None]:
    """
    Returns (effective_condition, preferred_platform).

    - condition: intent에서 명시된 경우 우선. 없으면 구매이력 평균가로 추론.
    - preferred_platform: preference_context.preferred_platform (ALL_PLATFORMS 내 값만)
    """
    effective_condition = condition
    if not effective_condition:
        avg = (preference_context.get("price_range") or {}).get("avg") or 0
        for threshold, inferred in _AVG_PRICE_CONDITION:
            if 0 < avg <= threshold:
                effective_condition = inferred
                break

    preferred_platform = preference_context.get("preferred_platform") or None
    if preferred_platform not in ALL_PLATFORMS:
        preferred_platform = None

    return effective_condition, preferred_platform

_llm: BaseChatModel | None = None


def _get_llm() -> BaseChatModel:
    global _llm
    if _llm is None:
        # retry_owner="application": _run_scoring_llm이 retry_call()로 이 호출을
        # 감싸므로 SDK 자체 재시도는 꺼서 중첩 재시도를 막는다.
        _llm = get_llm("product", temperature=0, max_tokens=800, retry_owner="application")
    return _llm


def _format_products(products: list[dict[str, Any]]) -> str:
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


_NUM_TO_ALPHA = {str(i + 1): chr(ord("A") + i) for i in range(26)}


def _normalize_label(lbl: str) -> str:
    s = str(lbl).strip().upper()
    # "1" → "A", "2" → "B" 숫자 형식
    if s in _NUM_TO_ALPHA:
        return _NUM_TO_ALPHA[s]
    # "[B] 상품명..." 형식에서 첫 번째 레이블 추출
    m = re.match(r'^\[([A-Z])\]', s)
    if m:
        return m.group(1)
    # 단일 알파벳
    if len(s) == 1 and s.isalpha():
        return s
    # 첫 번째 알파벳 문자 (마지막 수단)
    for c in s:
        if c.isalpha():
            return c
    return s


class _RankResult(BaseModel):
    ranked_labels: list[str]
    filtered_out_labels: list[str] = []


# ── Stage4: 스코어링. 판단(LLM)=axis_weight+tier3 매칭, 계산(코드)=정규화/합산 ──

class AxisWeight(BaseModel):
    axis: Literal["price", "review", "preference"]
    weight: float
    reasoning: str


class PreferenceItemScore(BaseModel):
    """
    soft_preferences 항목 하나 × 후보 하나에 대한 개별 판정.
    항목을 뭉쳐서 한 번에 판정하면 서로 다른 방향을 가리키는 신호(예:
    "저가"와 "프리미엄"이 동시에 감지된 경우)의 근거가 뭉개지므로,
    항목 단위로 쪼개서 판정한 뒤 aggregator에서 후보별 평균을 낸다.
    """
    candidate_id: str
    preference_item: str
    match_level: Literal["강한부합", "부합", "중립", "배치"]
    reasoning: str


class ScoringLLMOutput(BaseModel):
    axis_weights: list[AxisWeight] = Field(default_factory=list)
    preference_item_scores: list[PreferenceItemScore] = Field(default_factory=list)
    conflict_note: str | None = None


# soft_preferences가 과도하게 길어지면 preference_item_scores가
# (항목 수 × 후보 수)만큼 불어나 프롬프트 토큰이 커진다 — 상한을 둔다.
_MAX_SOFT_PREFERENCES = 5


def _assign_candidate_ids(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    tagged = []
    for i, c in enumerate(candidates[:26]):
        item = dict(c)
        item["_candidate_id"] = labels[i]
        tagged.append(item)
    return tagged


def _format_soft_preferences(signals: list[dict[str, Any]]) -> str:
    """
    RoutedSignal(dict)을 프롬프트용 텍스트로. priority_resolver.rank_by_recency가
    이미 최근 순으로 정렬해서 넘겨주므로, 순서 자체가 recency 정보다
    (목록 위쪽일수록 최근). purchase_history 소스만 실제 timestamp(구매일)가
    있어서 같이 보여준다 — 그 외(general_context/session_smalltalk)는
    timestamp가 없다 (Priority Resolver의 카테고리 규칙/발화 순서로 이미
    정렬 반영됨, computed_at 같은 걸 억지로 채우지 않는다).
    """
    if not signals:
        return "없음"
    lines = []
    for i, s in enumerate(signals, 1):
        value = s.get("value", "")
        ts = s.get("timestamp")
        source = s.get("source", "")
        detail = f" (출처:{source}, 구매일:{ts})" if ts else f" (출처:{source})" if source else ""
        lines.append(f"{i}. {value}{detail}")
    return "\n".join(lines)


def _run_scoring_llm(
    tagged_candidates: list[dict[str, Any]],
    keywords: list[str],
    condition: str | None,
    soft_preferences: list[dict[str, Any]],
) -> ScoringLLMOutput:
    soft_preferences = soft_preferences[:_MAX_SOFT_PREFERENCES]
    prompt = SCORING_PROMPT.format(
        keywords=json.dumps(keywords, ensure_ascii=False),
        condition=condition or "없음",
        soft_preferences=_format_soft_preferences(soft_preferences),
        formatted_candidates=_format_products(tagged_candidates),
    )
    structured = _get_llm().with_structured_output(ScoringLLMOutput, method="json_schema")
    result = retry_call(structured.invoke, [HumanMessage(content=prompt)])
    return result if isinstance(result, ScoringLLMOutput) else ScoringLLMOutput()


def _fails_safety_constraints(product: dict[str, Any], safety_constraints: list[str]) -> bool:
    """
    tier1(알레르기/식이제약) binary 배제. nutrition_info.allergens에 실제로
    태깅된 성분만 본다 — 상품명 substring 매칭이 아님 (오탐 줄이려는 목적).
    nutrition_info가 아예 없는 상품(연동 전 mcp 결과 등)은 판단 불가이므로
    안전 쪽으로 보수적으로 배제한다.
    """
    if not safety_constraints:
        return False
    nutrition = product.get("nutrition_info")
    if not nutrition:
        return True
    allergens = set(nutrition.get("allergens") or [])
    return bool(allergens & set(safety_constraints))


def _filter_results(
    products: list[dict[str, Any]],
    exclude_keywords: list[str],
    safety_constraints: list[str] | None = None,
) -> list[dict[str, Any]]:
    filtered = []
    for p in products:
        if p.get("is_sold_out"):
            continue
        if not p.get("product_url"):
            continue
        if p.get("price") is None:
            continue
        name = p.get("product_name", "").lower()
        brand = str(p.get("brand") or "").lower()
        if any(ex.lower() in name or ex.lower() in brand for ex in exclude_keywords):
            continue
        if _fails_safety_constraints(p, safety_constraints or []):
            continue
        filtered.append(p)
    return filtered


def _baseline_rank(candidates: list[dict[str, Any]], keywords: list[str]) -> list[dict[str, Any]]:
    """LLM 스코어링 실패 시 결정론적 폴백(Graceful Degradation).

    candidates는 이미 _filter_results로 안전조건/명시적 제외를 통과한 상태이므로
    별도 안전 필터링 없이, 키워드 매치 개수 → 평점 → 리뷰 수 → product_url(안정적
    tie-break) 순으로만 정렬한다. 동일 입력이면 항상 동일 순서가 나온다."""
    kw_lower = [k.lower() for k in keywords if k]

    def _keyword_match_count(p: dict[str, Any]) -> int:
        name = str(p.get("product_name") or "").lower()
        brand = str(p.get("brand") or "").lower()
        return sum(1 for k in kw_lower if k in name or k in brand)

    def _sort_key(p: dict[str, Any]) -> tuple:
        return (
            -_keyword_match_count(p),
            -float(p.get("rating") or 0),
            -int(p.get("review_count") or 0),
            str(p.get("product_url") or ""),
        )

    return sorted(candidates, key=_sort_key)


def _rank_with_metadata(
    candidates: list[dict[str, Any]],
    keywords: list[str],
    condition: str | None,
    preference_context: dict[str, Any],
) -> dict[str, Any]:
    """
    Stage4: 판단(LLM, 1콜)=axis_weight+tier3 매칭 → 계산(코드, aggregator)=
    정규화/카테고리→숫자/가중합. 반환 모양은 기존과 동일하게 유지
    (evals/run_experiment.py가 이 키들을 그대로 소비함) — ranked_products
    각 항목에 final_score/axis_contributions/reasoning 등이 추가로 실린다.
    """
    tagged = _assign_candidate_ids(candidates)
    soft_preferences = (preference_context.get("soft_preferences") or [])[:_MAX_SOFT_PREFERENCES]
    try:
        scoring = _run_scoring_llm(tagged, keywords, condition, soft_preferences)
        # soft_preferences 자체가 없으면 preference_item_scores가 비는 게 정상
        # (채점할 항목이 없음, aggregate()도 빈 items를 중립점수로 안전하게
        # 처리한다) — soft_preferences가 있는데도 LLM이 안 채운 경우만 실패로 본다.
        if soft_preferences and not scoring.preference_item_scores:
            raise ValueError("empty_preference_item_scores")

        fixed_normalized = normalize_fixed_axes(tagged)
        weights = normalize_weights({aw.axis: aw.weight for aw in scoring.axis_weights})

        # candidate_id별로 항목별 판정을 묶는다 — aggregator가 후보 단위 평균을 낸다.
        items_by_id: dict[str, list[PreferenceItemScore]] = {}
        for item in scoring.preference_item_scores:
            cid = _normalize_label(item.candidate_id)
            items_by_id.setdefault(cid, []).append(item)

        ranked = aggregate(tagged, fixed_normalized, items_by_id, weights)

        agent_logger.log_scoring_agent(
            {
                "candidates": len(candidates), "keywords": keywords,
                "condition": condition, "soft_preferences": soft_preferences,
            },
            {
                "axis_weights": [aw.model_dump() for aw in scoring.axis_weights],
                "weights_normalized": weights,
                "conflict_note": scoring.conflict_note,
                "ranked_top": ranked[0].get("product_name") if ranked else None,
                "ranked_top_score": ranked[0].get("final_score") if ranked else None,
            },
        )

        return {
            "ranked_products": ranked,
            "tool_call_success": True,
            "tool_call_error": None,
            "axis_weights": [aw.model_dump() for aw in scoring.axis_weights],
            "conflict_note": scoring.conflict_note,
            "ranking_mode": "llm",
            "degraded_mode": False,
            "failure_stage": None,
        }
    except Exception as e:
        fc = classify_failure(e)
        agent_logger.log_scoring_fallback(
            {"candidates": len(candidates), "keywords": keywords, "condition": condition}, str(e),
        )
        agent_logger.log_graceful_degradation(node="product_agent", reason=f"{fc.value}:{e}", stage="scoring_llm")
        return {
            "ranked_products": _baseline_rank(candidates, keywords),
            # 검색(tool)은 성공했고 스코어링 LLM만 실패한 것이므로 이 필드는
            # 보조 신호로만 쓴다 — 실제 축소 여부는 ranking_mode/degraded_mode로 판단.
            "tool_call_success": False,
            "tool_call_error": str(e),
            "ranking_mode": "baseline",
            "degraded_mode": True,
            "failure_stage": "scoring_llm",
        }


def product_agent_node(state: ProductAgentInput) -> ProductAgentUpdate:
    intent = state.get("intent")
    keywords = state.get("keywords") or []
    exclude_keywords = state.get("exclude_keywords") or []
    condition = state.get("condition")
    current_idx = state.get("current_product_index") or 0
    existing_ranked = state.get("recommended_products") or []
    recommendation_context = state.get("recommendation_context") or {}
    preference_context = recommendation_context.get("preference_context") or {}

    if not keywords or all(k in ["그거", "저번에", "그것", "저것"] for k in keywords):
        return {
            "search_results": [],
            "stage": "idle",
            "error": "invalid_keywords",
            "last_agent": "product_agent",
            "pending_action": {"type": "clarification", "message": _no_results_message([])},
        }

    # ── next/deny: 재검색 없이 다음 후보 ──
    if intent in ("next", "deny") and existing_ranked:
        if condition:
            rank_meta = _rank_with_metadata(existing_ranked, keywords, condition, preference_context)
            reranked = rank_meta["ranked_products"]
            top_product = reranked[0] if reranked else None
            if not top_product:
                return {
                    "stage": "idle",
                    "error": "no_relevant_products",
                    "last_agent": "product_agent",
                    "pending_action": {"type": "clarification", "message": _missing_product_message(keywords)},
                }
            agent_logger.log_product_agent(
                {"intent": intent, "rerank": True, "condition": condition},
                {"selected_product": top_product},
            )
            return {
                "selected_product": top_product,
                "product_url": top_product.get("product_url"),
                "recommended_products": reranked,
                "current_product_index": 0,
                "stage": "searching",
                "quantity": None,
                "last_agent": "product_agent",
                "error": None,
                "ranking_mode": rank_meta.get("ranking_mode"),
                "degraded_mode": rank_meta.get("degraded_mode", False),
                "failure_stage": rank_meta.get("failure_stage"),
            }

        next_idx = current_idx + 1
        if next_idx >= len(existing_ranked):
            return {
                "stage": "searching",
                "error": "no_more_products",
                "last_agent": "product_agent",
                "pending_action": {
                    "type": "no_more_products",
                    "message": _no_more_products_message(keywords),
                },
            }
        next_product = existing_ranked[next_idx]
        agent_logger.log_product_agent(
            {"intent": intent, "next_idx": next_idx},
            {"selected_product": next_product},
        )
        return {
            "selected_product": next_product,
            "product_url": next_product.get("product_url"),
            "recommended_products": existing_ranked,
            "current_product_index": next_idx,
            "stage": "searching",
            "quantity": None,
            "last_agent": "product_agent",
            "error": None,
        }

    # ── 전체 플랫폼 동시 검색 ──
    query = " ".join(keywords)
    effective_condition, preferred_platform = _derive_search_params(condition, preference_context)
    sort = CONDITION_MAP.get(effective_condition, "relevance") if effective_condition else "relevance"

    agent_logger.log(
        f"[product_agent] 검색 | query={query}  sort={sort}"
        f"  preferred_platform={preferred_platform}"
        f"  (condition={condition!r} → effective={effective_condition!r})"
    )
    raw_results = search_products(
        query=query,
        platforms=ALL_PLATFORMS,
        condition=sort,
        preferred_platform=preferred_platform,
    )
    candidates = _filter_results(raw_results, exclude_keywords, preference_context.get("safety_constraints"))

    if not candidates:
        return {
            "search_query": query,
            "stage": "idle",
            "error": "no_candidates",
            "last_agent": "product_agent",
            "pending_action": {"type": "clarification", "message": _missing_product_message(keywords)},
        }

    agent_logger.log(f"[product_agent] 랭킹 | 후보 {len(candidates)}개")
    rank_meta = _rank_with_metadata(candidates, keywords, condition, preference_context)
    ranked_products = rank_meta["ranked_products"]

    top_product = ranked_products[0] if ranked_products else None
    if not top_product:
        return {
            "search_query": query,
            "stage": "idle",
            "error": "no_relevant_products",
            "last_agent": "product_agent",
            "pending_action": {"type": "clarification", "message": _missing_product_message(keywords)},
        }

    agent_logger.log_product_agent(
        {"intent": intent, "candidates": len(candidates), "ranked": len(ranked_products)},
        {"selected_product": top_product},
    )
    return {
        "search_results": candidates,
        "search_query": query,
        "selected_product": top_product,
        "product_url": top_product.get("product_url"),
        "recommended_products": ranked_products,
        "current_product_index": 0,
        "stage": "searching",
        "quantity": None,
        "last_agent": "product_agent",
        "error": None,
        "ranking_mode": rank_meta.get("ranking_mode"),
        "degraded_mode": rank_meta.get("degraded_mode", False),
        "failure_stage": rank_meta.get("failure_stage"),
    }
