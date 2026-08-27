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
from src.utils.product_identity import (
    ProductIdentity,
    ComparisonResult,
    build_identity_from_request,
    brand_appears_in,
    compare_identities,
    normalize_brand,
)
from src.agents.product_resolver import ProductResolver, build_match_evidence

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


def _ambiguous_candidates_message(keywords: list[str]) -> str:
    label = keywords[0] if keywords else "그 상품"
    return f"{label}에 해당하는 상품이 여러 개 있는데, 정확히 어떤 건지 확실하지 않아요. 조금 더 구체적으로 말씀해 주시겠어요?"


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


def _gated_identity_for_mode(product_request: dict[str, Any]) -> ProductIdentity:
    """match_mode별로 어떤 조건까지 하드 체크 대상인지 결정한다(WON-22 Unit 4
    정책, Unit 7에서 substitution_scope 반영):
      category      — category 일치만(브랜드/사이즈는 검사 대상 아님)
      brand         — brand까지 일치해야 함(사이즈는 검사 안 함)
      exact_product — brand + variant/size까지 전부 일치해야 함
    substitution_scope에 "brand"가 있으면(대체품 동의로 브랜드까지 완화)
    브랜드 검사를 건너뛴다. "specifics"가 있으면(용량/옵션만 완화 동의)
    exact_product를 brand 수준으로 낮춘다(variant/size 검사 제외, 브랜드는
    유지) — "동의 범위 외 조건은 계속 유지"라는 완료 조건이 여기서
    보장된다. compare_identities는 identity에 실제로 채워진 필드만 검사
    하므로, 여기서 검사 대상이 아닌 필드를 아예 비워서 넘기면 자동으로
    빠진다(별도 if 분기 없이 하나의 compare_identities 호출로 통일)."""
    match_mode = product_request.get("match_mode", "category")
    scope = set(product_request.get("substitution_scope") or [])
    brand = None if "brand" in scope else product_request.get("brand")
    if match_mode == "category" or not brand:
        return ProductIdentity(normalized_brand="", normalized_product_name="")
    if match_mode == "brand" or "specifics" in scope:
        return ProductIdentity(normalized_brand=normalize_brand(brand), normalized_product_name="")
    return build_identity_from_request(product_request)  # exact_product, 완화 동의 없음


_SUBSTITUTION_FIELD_LABELS = {"specifics": "다른 용량", "brand": "다른 브랜드"}


def _offerable_substitution_fields(product_request: dict[str, Any]) -> list[str]:
    """지금 이 요청에서 추가로 제안할 수 있는 완화 항목(WON-22 Unit 7). 이미
    동의한(substitution_scope) 항목은 다시 제안하지 않는다 — 전부 동의했는데도
    후보가 없으면(완전한 NOT_FOUND) 빈 리스트를 반환해, 더 이상 대체품을
    제안하지 않고 최종 no_candidates로 끝나게 한다."""
    match_mode = product_request.get("match_mode")
    already = set(product_request.get("substitution_scope") or [])
    offerable = []
    if match_mode == "exact_product" and "specifics" not in already:
        offerable.append("specifics")
    if match_mode in ("brand", "exact_product") and "brand" not in already:
        offerable.append("brand")
    return offerable


def _substitution_offer_message(product_request: dict[str, Any], offerable: list[str]) -> str:
    parts = [p for p in (product_request.get("brand"), product_request.get("variant"), product_request.get("size")) if p]
    label = " ".join(parts) or (product_request.get("category") or "그 상품")
    options = "이나 ".join(_SUBSTITUTION_FIELD_LABELS[f] for f in offerable)
    return f"{label}는 찾지 못했어요. {options}도 찾아볼까요?"


def enforce_hard_constraints(
    candidates: list[dict[str, Any]], product_request: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """ProductRequest 기반 필수조건 필터(WON-22 Unit 4) — 조건 불일치 후보가
    점수와 무관하게 랭킹에 아예 들어가지 못하게 차단한다. 기존
    _matches_requested_keywords(any/OR — keywords 중 하나만 맞아도 통과)의
    허술함을 대체한다. product_request가 없으면(Unit 2가 아직 안 채운 경로,
    예: buy가 아닌 intent) 아무것도 거르지 않고 그대로 통과시킨다 — 이
    함수는 product_request가 있을 때만 적용되는 추가 계층이지, 기존 검색
    결과 자체를 재현하지 않는다.

    반환: (survivors, rejected) — rejected의 각 원소는 {"product_name":...,
    "mismatches": [...]} 로 탈락 이유를 사람이 읽을 수 있게 남긴다(Unit 5의
    "왜 이 후보가 안 맞는지" 설명, 로그 확인용)."""
    if not product_request:
        return candidates, []

    excluded_brands = product_request.get("excluded_brands") or []
    identity = _gated_identity_for_mode(product_request)

    survivors: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for p in candidates:
        haystack = f"{p.get('product_name') or ''} {p.get('brand') or ''}"
        mismatches: list[str] = []
        for excluded in excluded_brands:
            if brand_appears_in(haystack, excluded):
                mismatches.append(f"excluded_brand: 제외 요청한 브랜드 '{excluded}'가 후보에 포함됨")
        mismatches.extend(compare_identities(identity, haystack).mismatches)

        if mismatches:
            rejected.append({"product_name": p.get("product_name"), "mismatches": mismatches})
        else:
            survivors.append(p)
    return survivors, rejected


def _filter_results(
    products: list[dict[str, Any]],
    exclude_keywords: list[str],
    safety_constraints: list[str] | None = None,
    requested_keywords: list[str] | None = None,
    product_request: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    filtered = []
    for p in products:
        if p.get("is_sold_out"):
            continue
        if not p.get("product_url"):
            continue
        if p.get("price") is None:
            continue
        # WON-22 Unit 8 — 이중 방어. mock_search_product는 이제 표시 없는
        # placeholder(상품 A 등)를 자동으로 안 돌려주지만, 혹시 다른 경로
        # (테스트가 직접 주입 등)로 is_placeholder=True인 후보가 들어와도
        # 여기서 한 번 더 걸러낸다 — 운영 후보 경로에 fixture가 절대 안
        # 섞이게 하는 마지막 안전판(완료 조건: "운영 후보 필터에서
        # placeholder 차단").
        if p.get("is_placeholder"):
            continue
        # product_request가 있으면(Unit 2가 buy 발화를 구조화해둔 경우) any(OR)
        # 기반 _matches_requested_keywords를 건너뛴다(WON-22 Unit 4 — "기존
        # _matches_requested_keywords(any) 의존 제거") — 대신 product_agent_node
        # 에서 이 함수가 반환한 결과에 enforce_hard_constraints를 별도로 적용한다
        # (한 후보에 여러 필터가 섞이지 않게 단계를 분리). product_request가
        # 없는 경로(예: buy가 아닌 intent)는 기존 방식을 그대로 유지 — 회귀 없음.
        if not product_request and not _matches_requested_keywords(p, requested_keywords or []):
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


# WON-22 Unit 6 — rank_products(_rank_with_metadata, 아래) vs rank_offers(이
# 함수)는 랭킹 "대상의 의미"가 다르다: rank_products는 category/brand 요청의
# 서로 다른 제품을 비교하는 것(취향/가중치 판단이 필요해 LLM 스코어링을 씀).
# rank_offers는 ProductResolver가 이미 "같은 제품"이라고 확정한 후보들 사이의
# 판매처만 비교하는 것 — 브랜드/제품명 같은 취향 판단이 필요 없고, 가격/배송/
# 리뷰 같은 객관적 기준만 남는다. 그래서 LLM을 아예 안 쓰고 결정론적으로만
# 정렬한다(지연시간/비용 절감 + 같은 입력엔 항상 같은 순서 보장).
_OFFER_SORT_PRIORITY: dict[str, str] = {
    "최저가": "price", "가성비": "price",
    "무료배송": "free_shipping",
    "빠른배송": "delivery",
    "인기순": "reviews", "리뷰좋은": "reviews",
}
_FAST_DELIVERY_LABELS = ("로켓배송", "새벽배송", "당일배송", "익일배송")


def _offer_sort_key(condition: str | None):
    priority = _OFFER_SORT_PRIORITY.get(condition or "", "price")

    def key(p: dict[str, Any]) -> tuple:
        price = p.get("price") if p.get("price") is not None else float("inf")
        delivery_fee = p.get("delivery_fee") if p.get("delivery_fee") is not None else float("inf")
        is_slow = 0 if any(label in str(p.get("delivery") or "") for label in _FAST_DELIVERY_LABELS) else 1
        neg_reviews = -(p.get("review_count") or 0)
        if priority == "free_shipping":
            return (delivery_fee, price, is_slow, neg_reviews)
        if priority == "delivery":
            return (is_slow, price, delivery_fee, neg_reviews)
        if priority == "reviews":
            return (neg_reviews, price, delivery_fee, is_slow)
        return (price, delivery_fee, is_slow, neg_reviews)  # 기본값: 최저가/가성비

    return key


def rank_offers(candidates: list[dict[str, Any]], condition: str | None = None) -> list[dict[str, Any]]:
    """동일 identity(같은 제품)의 서로 다른 판매처(오퍼)를 가격/배송/리뷰
    기준으로 결정론적으로 정렬한다. 명시 조건(condition)이 있으면 그 기준을
    최우선으로, 없으면 최저가를 기본값으로 쓴다 — 완전히 같은 제품이면
    가격이 가장 직접적인 차별화 요소라는 게 기본 가정(과설계 방지, 필요해
    지면 조건 늘리기)."""
    return sorted(candidates, key=_offer_sort_key(condition))


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


def validate_selected_product(
    selected_product: dict[str, Any] | None, product_request: dict[str, Any] | None,
) -> ComparisonResult:
    """WON-22 Unit 9 — 응답/장바구니 진입 직전 마지막 안전판. Unit 4
    (enforce_hard_constraints)가 이미 선택 이전에 같은 종류의 검사를 하지만,
    이건 "실제로 반환되는 결과 자체"를 독립적으로 다시 재검증하는 별도
    계층이다 — 검색/선택 경로가 여러 개(next/deny 재랭킹, exact_product
    분기, 같은 identity 오퍼 분기 등)라 한쪽 경로에서 실수로 검증을
    빠뜨려도 여기서 최종적으로 잡히게 한다(단일 지점 신뢰 금지, 완료 조건
    "Product Agent가 잘못된 결과를 내도 사용자에게 노출되지 않음")."""
    if product_request is None:
        return ComparisonResult(matches=True, mismatches=[])
    if selected_product is None:
        return ComparisonResult(matches=False, mismatches=["no_selected_product: 선택된 상품이 없음"])

    mismatches: list[str] = []
    if selected_product.get("is_placeholder"):
        mismatches.append("placeholder: 표시된 fixture 상품이 선택됨(WON-22 Unit 8 위반)")
    if not selected_product.get("product_url"):
        mismatches.append("missing_url: 주문 가능한 URL이 없음")

    haystack = f"{selected_product.get('product_name') or ''} {selected_product.get('brand') or ''}"
    for excluded in product_request.get("excluded_brands") or []:
        if brand_appears_in(haystack, excluded):
            mismatches.append(f"excluded_brand: 제외 요청한 브랜드 '{excluded}'가 선택됨")

    identity = _gated_identity_for_mode(product_request)
    mismatches.extend(compare_identities(identity, haystack).mismatches)

    return ComparisonResult(matches=not mismatches, mismatches=mismatches)


def _validate_before_return(
    result: dict[str, Any], product_request: dict[str, Any] | None,
) -> dict[str, Any]:
    """product_agent_node의 모든 반환 경로가 여기를 거친다(WON-22 Unit 9).
    selected_product가 없거나 product_request가 없으면 그대로 통과 — 이건
    "선택은 됐는데 조건을 어겼는지"만 잡는 게이트지, 정상적인 no_candidates/
    clarification 응답까지 건드리지 않는다."""
    selected = result.get("selected_product")
    if not selected or not product_request:
        return result
    validation = validate_selected_product(selected, product_request)
    if validation.matches:
        return result
    agent_logger.log(
        f"[product_agent] Unit 9 최종 검증 실패(selection_validation_failed): "
        f"{selected.get('product_name')!r} - {validation.mismatches}"
    )
    label = product_request.get("brand") or product_request.get("category") or "그 상품"
    return {
        "search_query": result.get("search_query"),
        "stage": "idle",
        "error": "selection_validation_failed",
        "last_agent": "product_agent",
        "selected_product": None,
        "pending_action": {
            "type": "clarification",
            "message": f"{label} 정보를 다시 확인하는 중이에요. 잠시 후 다시 말씀해 주시겠어요?",
        },
    }


def product_agent_node(state: ProductAgentInput) -> ProductAgentUpdate:
    result = _product_agent_node_impl(state)
    return _validate_before_return(result, state.get("product_request"))


def _product_agent_node_impl(state: ProductAgentInput) -> ProductAgentUpdate:
    intent = state.get("intent")
    keywords = state.get("keywords") or []
    exclude_keywords = state.get("exclude_keywords") or []
    condition = state.get("condition")
    product_request = state.get("product_request")
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
        requested_keywords=keywords, product_request=product_request,
    )
    # WON-22 Unit 4 — 하드 조건(브랜드/제외 브랜드/exact_product의 사이즈)
    # 불일치 후보를 점수와 무관하게 랭킹 이전에 차단한다. product_request가
    # 없으면(Unit 2가 안 채운 경로) candidates 그대로 통과 — 회귀 없음.
    candidates, rejected_by_constraints = enforce_hard_constraints(candidates, product_request)
    if rejected_by_constraints:
        agent_logger.log(
            f"[product_agent] 하드 조건 탈락 {len(rejected_by_constraints)}건: "
            f"{[(r['product_name'], r['mismatches']) for r in rejected_by_constraints]}"
        )

    if not candidates:
        # WON-22 Unit 7 — brand/exact_product 요청인데 하드 조건을 만족하는
        # 후보가 하나도 없으면, 조용히 포기(clarification)하기 전에 조건을
        # 완화해도 될지 먼저 물어본다(자동 대체 금지가 완료 조건 — 물어보지
        # 않고 스스로 다른 브랜드/사이즈를 골라주면 안 됨).
        offerable = _offerable_substitution_fields(product_request) if product_request else []
        if offerable:
            return {
                "search_query": query,
                "stage": "idle",
                "error": "no_candidates",
                "last_agent": "product_agent",
                "pending_action": {
                    "type": "substitution_confirm",
                    "message": _substitution_offer_message(product_request, offerable),
                    "payload": {"product_request": product_request, "offered_fields": offerable},
                },
            }
        return {
            "search_query": query,
            "stage": "idle",
            "error": "no_candidates",
            "last_agent": "product_agent",
            "pending_action": {"type": "clarification", "message": _missing_product_message(keywords)},
        }

    # WON-22 Unit 5 — exact_product 요청은 일반 rank_products(취향/점수 기반
    # 랭킹)를 타지 않고 ProductResolver로 분리 처리한다. "여러 후보 중 그럴듯한
    # 걸 점수로 고르는" 로직에 exact_product를 섞으면, 조건이 안 맞는 후보를
    # 그럴듯한 이유로 조용히 골라버리는 문제(이 티켓의 발단)가 재발할 수 있다.
    if product_request and product_request.get("match_mode") == "exact_product":
        resolve_result = ProductResolver.resolve(product_request, candidates)

        if resolve_result.status == "not_found":
            return {
                "search_query": query,
                "stage": "idle",
                "error": "no_candidates",
                "last_agent": "product_agent",
                "pending_action": {"type": "clarification", "message": _missing_product_message(keywords)},
            }

        if resolve_result.status == "ambiguous":
            # 하드 조건은 통과했지만 서로 다른 identity가 섞여 있음 — 어느 걸
            # 원하는지 확실치 않으므로 자동으로 아무거나 고르지 않는다.
            return {
                "search_query": query,
                "stage": "idle",
                "error": "ambiguous_candidates",
                "last_agent": "product_agent",
                "pending_action": {"type": "clarification", "message": _ambiguous_candidates_message(keywords)},
            }

        if resolve_result.status == "selected":
            top_product = dict(resolve_result.selected)
            top_product["_match_evidence"] = resolve_result.match_evidence
            agent_logger.log_product_agent(
                {"intent": intent, "resolver_status": "selected"},
                {"selected_product": top_product},
            )
            return {
                "search_results": candidates,
                "search_query": query,
                "selected_product": top_product,
                "product_url": top_product.get("product_url"),
                "recommended_products": [top_product],
                "current_product_index": 0,
                "stage": "searching",
                "quantity": state.get("quantity"),
                "last_agent": "product_agent",
                "error": None,
            }

        # status == "same_identity_multiple" — 같은 제품을 여러 판매처가
        # 파는 경우. rank_products(취향 기반 LLM 랭킹)를 타지 않고 rank_offers
        # (가격/배송/리뷰 결정론적 정렬, Unit 6)로 판매처만 비교한다.
        ranked_offers = rank_offers(resolve_result.candidates, condition)
        top_offer = ranked_offers[0]
        top_offer = dict(top_offer)
        top_offer["_match_evidence"] = build_match_evidence(product_request, top_offer)
        agent_logger.log_product_agent(
            {"intent": intent, "resolver_status": "same_identity_multiple", "offers": len(ranked_offers)},
            {"selected_product": top_offer},
        )
        return {
            "search_results": resolve_result.candidates,
            "search_query": query,
            "selected_product": top_offer,
            "product_url": top_offer.get("product_url"),
            "recommended_products": ranked_offers,
            "current_product_index": 0,
            "stage": "searching",
            "quantity": state.get("quantity"),
            "last_agent": "product_agent",
            "error": None,
            "ranking_mode": "offer_deterministic",
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
