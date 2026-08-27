"""ProductResolver — exact_product 요청을 일반 랭킹(rank_products)과 분리해서
처리한다(WON-22 Unit 5). 별도 LangGraph Agent가 아니라 코드 모듈이다 —
product_agent.py가 이 모듈의 함수를 그대로 호출한다.

exact_product는 "여러 상품 중 뭐가 더 나은지 취향으로 고르는" 문제가 아니라
"사용자가 지목한 그 하나가 실제로 있는지 없는지"의 문제다 — 그래서 category/
brand 요청과 같은 랭킹 파이프라인을 타면 안 된다(랭킹은 "그럴듯한 후보 중
점수로 하나를 고르는" 로직이라, 진짜 exact_product 매칭을 요구하는 상황에
쓰면 조건 불일치 후보를 그럴듯한 점수로 조용히 골라버릴 위험이 있다 — 이
티켓이 애초에 고치려던 문제).

Unit 4(product_agent.enforce_hard_constraints)가 이미 브랜드/옵션/사이즈
하드 조건을 만족하지 않는 후보를 걸러낸 뒤 candidates를 이 모듈에 넘긴다는
전제로 동작한다."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from src.utils.product_identity import build_identity_from_candidate

ResolveStatus = Literal["not_found", "selected", "same_identity_multiple", "ambiguous"]


@dataclass
class ResolveResult:
    status: ResolveStatus
    selected: Optional[dict[str, Any]] = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    match_evidence: Optional[dict[str, Any]] = None


def _identity_grouping_key(product: dict[str, Any]) -> str:
    """같은 identity(=같은 제품, 판매처만 다름)인지 묶기 위한 key. 브랜드/
    사이즈는 이미 Unit 4가 요청과 일치하는 것만 통과시켰으므로 후보들 사이의
    변별력이 없다 — 남은 변수는 product_name 표기 차이뿐이라 이것만 본다."""
    identity = build_identity_from_candidate(product)
    return identity.normalized_product_name


def build_match_evidence(product_request: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """선택 근거 기록(완료 조건: "선택 결과에 match evidence 저장"). Unit 9
    (최종 선택 검증 게이트)나 "왜 이걸 골랐는지" 설명에 그대로 재사용 가능한
    형태로 남긴다 — LLM이 사후에 그럴싸한 이유를 지어내는 게 아니라, 실제로
    무엇을 어떻게 확인해서 골랐는지의 사실 기록이다."""
    return {
        "match_mode": product_request.get("match_mode"),
        "requested_brand": product_request.get("brand"),
        "requested_variant": product_request.get("variant"),
        "requested_size": product_request.get("size"),
        "candidate_name": candidate.get("product_name"),
    }


class ProductResolver:
    """exact_product 요청 전용 선택기.

    분기(티켓 원문 정책):
      - 일치 0개 → NOT_FOUND. 자동 대체 금지 — 브랜드만 같은 다른 SKU를
        조용히 고르지 않는다(WON-22의 핵심 동기, "서울우유 나100% 1L" 요청에
        아무 서울우유나 대신 내주던 문제).
      - 일치 1개 → 즉시 select.
      - 일치 여러 개이며 전부 같은 identity(같은 제품을 여러 판매처가 파는
        경우) → 그 판매처들 사이에서 고르는 문제이므로 offer ranking으로
        넘긴다(Unit 6에서 rank_offers로 정식 분리 예정 — 그 전까지 product_
        agent.py가 기존 _rank_with_metadata를 이 좁혀진 후보군에 재사용).
      - 서로 다른 identity가 섞여 있음 → 어느 게 진짜 사용자가 원한 건지
        알 수 없으므로 자동으로 고르지 않고 clarification으로 넘긴다.
    """

    @staticmethod
    def resolve(product_request: dict[str, Any], candidates: list[dict[str, Any]]) -> ResolveResult:
        if not candidates:
            return ResolveResult(status="not_found", candidates=[])

        if len(candidates) == 1:
            only = candidates[0]
            return ResolveResult(
                status="selected", selected=only, candidates=candidates,
                match_evidence=build_match_evidence(product_request, only),
            )

        keys = {_identity_grouping_key(p) for p in candidates}
        if len(keys) == 1:
            return ResolveResult(status="same_identity_multiple", candidates=candidates)
        return ResolveResult(status="ambiguous", candidates=candidates)
