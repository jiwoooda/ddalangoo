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
from src.utils.search_keywords import build_search_query
from src.utils.aggregator import aggregate, normalize_fixed_axes, normalize_weights
from src.utils.priority_resolver import _mentions_same_target
from src.utils.retry import classify_failure, retry_call

ALL_PLATFORMS = ["naver", "coupang", "kurly"]

# tier1 안전필터 폴백용 — nutrition_info가 없는 상품(mcp 실API 등)에서
# 라벨 자체가 상품명/카테고리에 그대로 안 나타나는 경우를 위한 구체어 확장.
_SAFETY_KEYWORD_EXPANSIONS: dict[str, list[str]] = {
    "유제품": ["우유", "치즈", "버터", "크림", "연유", "분유", "요거트", "요구르트", "유청", "카제인"],
    "유당불내증": ["우유", "치즈", "버터", "크림", "연유", "분유", "유당"],
    "계란": ["계란", "달걀", "난류", "마요네즈"],
    "난류": ["계란", "달걀", "난류", "마요네즈"],
    "땅콩": ["땅콩", "피넛"],
    "견과류": ["땅콩", "호두", "아몬드", "캐슈넛", "잣", "견과"],
    "밀": ["밀", "밀가루", "글루텐"],
    "글루텐": ["밀", "밀가루", "글루텐"],
    "대두": ["대두", "콩", "두유"],
    "갑각류": ["새우", "게", "갑각류"],
}

# 상품명에 이 라벨이 있으면 해당 제약은 통과시킨다(예: "우유"가 걸려도
# "락토프리"가 같이 적혀 있으면 유당불내증/유제품 제약은 통과). 성분을
# 실제로 검증한 게 아니라 제조사가 표기한 상품명 문구를 신뢰하는
# best-effort이므로, allergens/diet_restrictions 구분 없이 라벨 자체가
# 곧 안전 근거다 — 정확한 알레르기 판정이 필요하면 nutrition_info 연동이
# 별도로 필요하다.
_SAFETY_SAFE_LABELS: dict[str, list[str]] = {
    "유제품": ["락토프리", "무유당", "저유당", "소화가잘되는", "소화가 잘되는", "소화가 잘 되는"],
    "유당불내증": ["락토프리", "무유당", "저유당", "소화가잘되는", "소화가 잘되는", "소화가 잘 되는"],
    "설탕": ["무설탕", "저당", "제로", "무가당", "라이트"],
    "당": ["무설탕", "저당", "제로", "무가당", "라이트"],
}


def _strip_spaces(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _safety_fallback_keywords(label: str) -> list[str]:
    return _SAFETY_KEYWORD_EXPANSIONS.get(label, [label])


def _has_safe_label(label: str, haystack_no_space: str) -> bool:
    return any(_strip_spaces(safe) in haystack_no_space for safe in _SAFETY_SAFE_LABELS.get(label, []))


def _no_results_message(keywords: list[str]) -> str:
    label = keywords[0] if keywords else None
    if label:
        return f"죄송해요, {label}는 못 찾았어요. 다른 상품으로 다시 말씀해 주시겠어요?"
    return "죄송해요, 찾으시는 상품이 없었어요. 다른 상품으로 다시 말씀해 주시겠어요?"


def _missing_product_message(keywords: list[str]) -> str:
    return _no_results_message(keywords)


def _no_more_products_message(keywords: list[str]) -> str:
    label = keywords[0] if keywords else None
    if label:
        return f"{label}로는 더 보여드릴 상품이 없네요. 다른 상품을 찾아볼까요?"
    return "더 보여드릴 상품이 없네요. 다른 상품을 찾아볼까요?"

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
    태깅된 성분이 있으면 그걸로 정확히 판정한다 (상품명 substring 매칭이
    아님 — 오탐 줄이려는 목적).

    nutrition_info가 아예 없는 상품(mcp 실API 등 성분표 연동 전 결과)은
    상품명/카테고리/브랜드 텍스트를 _SAFETY_KEYWORD_EXPANSIONS로 확장한
    구체어와 매칭하는 best-effort 폴백으로 대신한다 — 완전한 성분 검증은
    아니지만, 예전처럼 nutrition_info 없다고 무조건 전체 차단하는 것보다는
    실제로 위험해 보이는 카테고리만 걸러낸다.

    단, 상품명에 _SAFETY_SAFE_LABELS(락토프리/무유당/소화가 잘되는 등)가
    함께 적혀 있으면 그 제약에 한해 통과시킨다 — 제조사 표기를 신뢰하는
    것이므로 완벽한 성분 검증은 아니다.
    """
    if not safety_constraints:
        return False
    nutrition = product.get("nutrition_info")
    if nutrition:
        allergens = set(nutrition.get("allergens") or [])
        return bool(allergens & set(safety_constraints))

    haystack = " ".join([
        str(product.get("product_name") or ""),
        str(product.get("category_name") or ""),
        str(product.get("brand") or ""),
    ]).lower()
    haystack_no_space = _strip_spaces(haystack)
    for label in safety_constraints:
        if _has_safe_label(label, haystack_no_space):
            continue
        if any(_strip_spaces(kw.lower()) in haystack_no_space for kw in _safety_fallback_keywords(label)):
            return True
    return False


def _matches_requested_keywords(product: dict[str, Any], requested_keywords: list[str]) -> bool:
    """원 요청(state.keywords)과 실제로 관련 있는 후보인지 검증.

    검색 쿼리에 keyword_additions("락토프리 우유" 등)를 붙이면 검색엔진이
    "락토프리"만 보고 원 요청과 무관한 카테고리(예: 락토프리 단백질 보충제)를
    끼워 넣을 수 있다 — 실측에서 "우유 사줘"가 유청 단백질 파우더로 새는
    사례가 확인됐다. 원 키워드가 상품명/브랜드에 하나도 안 걸리면 애초에
    "이번 요청에 대한 답"이 아니므로, 락토프리 같은 속성 매칭 이전에 걸러낸다.
    """
    if not requested_keywords:
        return True
    name = str(product.get("product_name") or "").lower()
    brand = str(product.get("brand") or "").lower()
    return any(kw.lower() in name or kw.lower() in brand for kw in requested_keywords if kw)


def _filter_results(
    products: list[dict[str, Any]],
    exclude_keywords: list[str],
    safety_constraints: list[str] | None = None,
    requested_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    filtered = []
    for p in products:
        if p.get("is_sold_out"):
            continue
        if not p.get("product_url"):
            continue
        if p.get("price") is None:
            continue
        if not _matches_requested_keywords(p, requested_keywords or []):
            continue
        name = p.get("product_name", "").lower()
        brand = str(p.get("brand") or "").lower()
        name_no_space = _strip_spaces(name + " " + brand)
        # "설탕" 배제가 "무설탕"까지 물어가는 negation-prefix 오탐 방지 —
        # tier1과 동일하게 안전라벨이 붙어 있으면 그 배제는 통과시킨다.
        if any(
            _strip_spaces(ex.lower()) in name_no_space and not _has_safe_label(ex, name_no_space)
            for ex in exclude_keywords
        ):
            continue
        if _fails_safety_constraints(p, safety_constraints or []):
            continue
        filtered.append(p)
    return filtered


def _baseline_rank(
    candidates: list[dict[str, Any]],
    keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """LLM 스코어링 실패 시 결정론적 폴백(Graceful Degradation).

    candidates는 이미 _filter_results로 안전조건/명시적 제외를 통과한 상태이므로
    별도 안전 필터링 없이, 키워드 매치 개수 → 평점 → 리뷰 수 → product_url(안정적
    tie-break) 순으로만 정렬한다. 동일 입력이면 항상 동일 순서가 나온다.

    영양성분을 볼 수 없어 "설탕 없음"을 완벽히 검증할 방법이 없다 — exclude_keywords에
    당분 관련 배제(설탕/당)가 있으면, 상품명에 _SAFETY_SAFE_LABELS로 안전 라벨(저당/
    무설탕/제로 등)이 붙은 후보를 최우선으로 정렬해서 "그나마 가장 저당에 가까운" 걸
    고른다 — 완벽한 필터링 대신 최선의 근사 선택."""
    kw_lower = [k.lower() for k in keywords if k]
    diet_boost_labels: set[str] = set()
    for ex in (exclude_keywords or []):
        diet_boost_labels.update(_SAFETY_SAFE_LABELS.get(ex, []))

    def _keyword_match_count(p: dict[str, Any]) -> int:
        name = str(p.get("product_name") or "").lower()
        brand = str(p.get("brand") or "").lower()
        return sum(1 for k in kw_lower if k in name or k in brand)

    def _diet_boost(p: dict[str, Any]) -> int:
        if not diet_boost_labels:
            return 0
        name_no_space = _strip_spaces(str(p.get("product_name") or "").lower())
        return sum(1 for label in diet_boost_labels if _strip_spaces(label) in name_no_space)

    def _sort_key(p: dict[str, Any]) -> tuple:
        return (
            -_diet_boost(p),
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
    exclude_keywords: list[str] | None = None,
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
            "ranked_products": _baseline_rank(candidates, keywords, exclude_keywords),
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
            rank_meta = _rank_with_metadata(existing_ranked, keywords, condition, preference_context, exclude_keywords)
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
    # keyword_additions(context_agent의 retrieval_signals)는 "유당불내증" →
    # "락토프리 우유"처럼 프로필 제약을 구체 검색어로 번역한 값인데, 이번
    # keywords와 무관한 신호까지 섞여 있을 수 있다(예: 오늘 "커피 원두"를
    # 검색 중인데 프로필의 유당불내증이 매턴 "락토프리 우유"로 번역돼 따라
    # 붙는 경우 — context_agent.py:638-642 참고). 오늘 keywords와 같은
    # 대상을 가리키는 addition만 골라 붙여서 무관한 카테고리 오염을 막는다.
    relevant_additions = [
        addition for addition in (preference_context.get("keyword_additions") or [])
        if any(_mentions_same_target(kw, addition) for kw in keywords)
    ]
    # LLM 분류기가 "당뇨 → 저당" 같은 retrieval 신호를 안정적으로 안 뽑는 경우가
    # 있어(모델 편차) exclude_keywords에 이미 확정된 배제어(설탕 등)가 있으면
    # _SAFETY_SAFE_LABELS로 대응하는 대표 라벨(저당 등)을 코드에서 직접
    # 쿼리에 붙인다 — LLM 신뢰도에 기대지 않는 결정론적 보강.
    # 단, exclude_keywords는 프로필 제약이면 오늘 뭘 사든 무조건 채워지므로
    # (safety_constraints가 매턴 무조건 병합됨) 관련성 체크 없이 붙이면
    # "사과 사줘"에도 "락토프리"가 붙어 엉뚱한 결과로 새는 오염이 실측
    # 확인됐다 — 오늘 keywords가 그 제약의 위험군(_safety_fallback_keywords,
    # 예: 유당불내증→우유/치즈/...)과 실제로 관련 있을 때만 붙인다.
    diet_query_additions = list(dict.fromkeys(
        _SAFETY_SAFE_LABELS[ex][0]
        for ex in exclude_keywords
        if ex in _SAFETY_SAFE_LABELS
        and any(
            _mentions_same_target(kw, risk_term)
            for kw in keywords
            for risk_term in _safety_fallback_keywords(ex)
        )
    ))
    query = build_search_query(keywords + relevant_additions + diet_query_additions)
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
    candidates = _filter_results(
        raw_results, exclude_keywords, preference_context.get("safety_constraints"),
        requested_keywords=keywords,
    )

    if not candidates:
        return {
            "search_query": query,
            "stage": "idle",
            "error": "no_candidates",
            "last_agent": "product_agent",
            "pending_action": {"type": "clarification", "message": _missing_product_message(keywords)},
        }

    agent_logger.log(f"[product_agent] 랭킹 | 후보 {len(candidates)}개")
    rank_meta = _rank_with_metadata(candidates, keywords, condition, preference_context, exclude_keywords)
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
        # 들어온 quantity를 그대로 돌려준다(무조건 None으로 리셋하지 않음) —
        # intent_agent가 이번 턴에 이미 "명시됐으면 숫자, 아니면 None"으로
        # 정확히 정리해서 넘겨준다(_search_intents 로직 참고). 여기서 무조건
        # None으로 리셋하면 "우유 3개 사줘"처럼 상품명과 수량을 함께 말한
        # 요청도 수량이 사라진다(실측 확인, fl-2026-08-19-001).
        "quantity": state.get("quantity"),
        "last_agent": "product_agent",
        "error": None,
        "ranking_mode": rank_meta.get("ranking_mode"),
        "degraded_mode": rank_meta.get("degraded_mode", False),
        "failure_stage": rank_meta.get("failure_stage"),
    }
