"""Product Identity 정규화 — 상품 두 개(사용자 요청 vs 실제 후보)가 "같은 것을
가리키는지" 판정하기 위한 결정론적 비교 유틸(WON-22 Unit 3).

설계 원칙(사용자와 합의한 하이브리드 구조):
- 기계적으로 정답이 하나로 정해지는 것(단위 환산, 공백/대소문자 정리, 브랜드가
  실제로 텍스트에 등장하는지)은 전부 규칙(이 파일의 결정론적 함수들)으로 확정한다.
  이 파일은 `src/utils/search_keywords.py`와 같은 급의 순수 유틸리티다 — 상태/
  에이전트에 결합하지 않고, 아직 어디에도 연결되지 않는다(product_agent.py는
  이번 Unit에서 미변경 — 실제 연결은 Unit 4/5).
- 규칙표로 다 못 따라잡는 애매한 이름 매칭(브랜드 별칭 등)은 `resolve_brand_
  ambiguity_llm`이 보조 신호로만 제공한다. **"사용자가 명시한 브랜드/제외
  브랜드를 어겼는지"의 최종 게이트는 항상 brand_appears_in(규칙)이다** — LLM
  보조 결과가 뭐라 하든 이 원칙은 이후 Unit(4/5)에서도 유지돼야 한다.
- "1L"과 "1000ml"처럼 문자열은 다르지만 같은 값을 가리키는 표기 차이가 실제
  운영 상품명에 존재한다(예: "서울우유 나100% 1000ml" — WON-22 Unit 0에서 실제
  쿠팡 검색으로 확인). 문자열 포함 여부만으로 exact match하면 이런 표기 차이를
  전부 "다른 상품"으로 오판한다 — 그래서 size는 항상 숫자로 변환해 비교한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

SizeFamily = Literal["volume", "weight"]


@dataclass(frozen=True)
class SizeValue:
    """정규화된 크기 — amount는 계열(family) 안에서의 최소 단위 환산값
    (volume→ml, weight→g). "1L"과 "1000ml"은 둘 다 SizeValue(1000.0, "volume")
    가 되어 등호 비교와 대소 비교(어느 게 더 큰지)가 둘 다 가능하다 — 후자는
    이번 Unit에서 안 쓰지만, Unit 6(size_preference="largest"/"smallest" 랭킹)
    이 그대로 재사용할 수 있게 값 자체를 비교 가능한 형태로 설계했다."""
    amount: float
    family: SizeFamily

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SizeValue):
            return NotImplemented
        # 부동소수점 오차 허용(예: "2.3L" 파싱 결과가 2299.999999...가 되는 경우 대비)
        return self.family == other.family and abs(self.amount - other.amount) < 1e-6

    def __lt__(self, other: "SizeValue") -> bool:
        if self.family != other.family:
            raise ValueError(f"단위 계열이 달라 비교 불가: {self.family} vs {other.family}")
        return self.amount < other.amount


# 긴 단위(kg/그램/밀리리터/리터)를 짧은 단위(g/l)보다 먼저 두지 않아도 regex
# 매칭 위치 자체가 다른 문자로 시작해 충돌은 없지만, 가독성을 위해 계열별로
# 묶어서 순서를 유지한다. 값은 "그 계열의 최소 단위로 환산했을 때 배율".
_VOLUME_UNITS: dict[str, float] = {
    "ml": 1.0, "밀리리터": 1.0,
    "l": 1000.0, "리터": 1000.0,
}
_WEIGHT_UNITS: dict[str, float] = {
    "g": 1.0, "그램": 1.0,
    "kg": 1000.0, "킬로그램": 1000.0,
}
_ALL_SIZE_UNITS: dict[str, tuple[float, SizeFamily]] = {
    **{u: (m, "volume") for u, m in _VOLUME_UNITS.items()},
    **{u: (m, "weight") for u, m in _WEIGHT_UNITS.items()},
}
# 정규식 alternation 순서: ml/kg처럼 다른 단위의 부분 문자열이 될 수 있는
# 짧은 단위(l, g)를 뒤로 둔다(예: "kg"가 "g"보다 먼저 시도돼야 "1kg"의
# "kg"를 온전히 잡는다 — 실제로는 시작 위치가 겹치지 않아 순서 무관하지만
# 방어적으로 긴 것부터 정렬).
_SIZE_UNIT_ALTERNATION = "|".join(
    sorted(_ALL_SIZE_UNITS, key=len, reverse=True)
)
_SIZE_PATTERN = re.compile(
    rf"(\d[\d,]*(?:\.\d+)?)\s*({_SIZE_UNIT_ALTERNATION})\b",
    re.IGNORECASE,
)

# 패키지 낱개 수(pack_count) 전용 — "200ml, 48개"의 "48개"처럼 후보 상품
# 자체의 패키징(한 박스에 몇 개 들었는지)을 가리킨다. **사용자 발화의
# "구매 수량"(얼마나 살지, 기존 intent_agent._parse_quantity/search_keywords.py
# 의 _QUANTITY_PHRASE가 이미 전담)과는 완전히 다른 개념이다** — 이 정규식은
# 후보 상품명(build_identity_from_candidate)에만 쓰고, 사용자 요청 텍스트
# 파싱에 재사용하지 않는다(혼동 방지, 이미 있는 quantity 파이프라인과 절대
# 안 섞을 것).
_COUNT_UNITS = ("구", "개입", "개", "입", "팩", "봉", "캔", "병", "통", "포")
_COUNT_PATTERN = re.compile(
    rf"(\d+)\s*({'|'.join(_COUNT_UNITS)})\b",
)


def parse_size(text: str) -> Optional[SizeValue]:
    """텍스트에서 처음 등장하는 용량/무게 표기를 정규화된 SizeValue로 변환.
    "1L", "1000ml", "2,300mL", "500g", "1kg" 전부 처리. 못 찾으면 None."""
    if not text:
        return None
    m = _SIZE_PATTERN.search(text)
    if not m:
        return None
    raw_amount, raw_unit = m.group(1), m.group(2)
    try:
        amount = float(raw_amount.replace(",", ""))
    except ValueError:
        return None
    multiplier, family = _ALL_SIZE_UNITS[raw_unit.lower()]
    return SizeValue(amount=amount * multiplier, family=family)


def parse_pack_count(text: str) -> Optional[int]:
    """"200ml, 48개"의 "48" 같은 패키지 낱개 수. 후보 상품명 파싱 전용
    (사용자 발화의 구매 수량과 혼동 금지 — 모듈 docstring 참고)."""
    if not text:
        return None
    m = _COUNT_PATTERN.search(text)
    if not m:
        return None
    return int(m.group(1))


_PUNCT_PATTERN = re.compile(r"[\s\-_/,.]+")


def normalize_brand(text: Optional[str]) -> str:
    """공백/구두점 정리 + 소문자화만 한다 — 별칭 사전(예: CJ↔씨제이)은 일부러
    안 만든다. 실제 브랜드 표기가 너무 다양해서 하드코딩 리스트로는 유지보수가
    안 따라간다는 게 이 설계의 출발점(사용자 지적) — 못 잡는 별칭은
    resolve_brand_ambiguity_llm이 보조한다."""
    if not text:
        return ""
    return _PUNCT_PATTERN.sub("", text).strip().lower()


def brand_appears_in(candidate_name: str, requested_brand: Optional[str]) -> bool:
    """정규화 후 candidate_name 안에 requested_brand가 실제로 등장하는지.
    **이게 "사용자가 명시한 브랜드를 어겼는지"를 최종 판정하는 유일한 하드
    게이트다** — resolve_brand_ambiguity_llm의 결과와 무관하게, Unit 4/5는
    항상 이 함수로 최종 확인해야 한다(브랜드 오선택을 실제로 막는 지점).
    requested_brand가 없으면(요청에 브랜드 지정이 없으면) 검증 대상이 아니므로
    True(통과)."""
    if not requested_brand:
        return True
    if not candidate_name:
        return False
    return normalize_brand(requested_brand) in normalize_brand(candidate_name)


@dataclass(frozen=True)
class ProductIdentity:
    normalized_brand: str
    normalized_product_name: str
    variant: Optional[str] = None
    size: Optional[SizeValue] = None
    pack_count: Optional[int] = None


def build_identity_from_candidate(product: dict) -> ProductIdentity:
    """실제 검색 결과(product_name이 자유 텍스트 위주)에서 정규식으로 파싱.
    product.get("brand")가 있으면 그대로 정규화해서 쓰고(mock 카탈로그처럼
    구조화된 brand 필드가 있는 경우), 없으면(실제 쿠팡 API 응답처럼 brand
    필드가 비어있는 경우가 실측으로 확인됨 — WON-22 Unit 0) 빈 문자열로
    둔다 — brand_appears_in은 이 필드가 아니라 product_name 원문을 직접
    검사하므로 여기 비어있어도 최종 검증에는 영향 없다."""
    name = str(product.get("product_name") or "")
    brand = product.get("brand")
    return ProductIdentity(
        normalized_brand=normalize_brand(brand) if brand else "",
        normalized_product_name=normalize_brand(name),
        variant=None,
        size=parse_size(name),
        pack_count=parse_pack_count(name),
    )


def build_identity_from_request(product_request: dict) -> ProductIdentity:
    """Unit 2가 이미 구조화해둔 필드(brand/size/variant)에서 정규화만 —
    파싱이 필요 없어 candidate 쪽보다 신뢰도가 높다. product_request.size가
    "1L" 같은 문자열이면 parse_size로 한 번 더 정규화해서 candidate의
    SizeValue와 동일한 형태로 맞춘다."""
    brand = product_request.get("brand")
    product_name = product_request.get("product_name")
    variant = product_request.get("variant")
    size_text = product_request.get("size")
    return ProductIdentity(
        normalized_brand=normalize_brand(brand) if brand else "",
        normalized_product_name=normalize_brand(product_name) if product_name else "",
        variant=variant,
        size=parse_size(size_text) if size_text else None,
        pack_count=None,
    )


@dataclass
class ComparisonResult:
    matches: bool
    mismatches: list[str] = field(default_factory=list)


def compare_identities(request: ProductIdentity, candidate_name: str) -> ComparisonResult:
    """request(ProductRequest에서 만든 identity)와 candidate_name(실제 후보
    상품명 원문) 비교. "문자열 포함 여부만으로 exact match" 하지 않는다 —
    size는 숫자 환산 비교, brand는 정규화 후 비교(단순 substring이되 공백/
    대소문자 차이는 흡수). 불일치 사유를 사람이 읽을 수 있는 문자열로 반환
    (디버깅 + Unit 5의 "왜 이 후보가 안 맞는지 설명" 용도로 그대로 재사용
    가능하게 설계)."""
    mismatches: list[str] = []

    if request.normalized_brand and not brand_appears_in(candidate_name, request.normalized_brand):
        mismatches.append(
            f"brand_mismatch: 요청 브랜드 '{request.normalized_brand}'가 후보명에 없음"
        )

    if request.size is not None:
        candidate_size = parse_size(candidate_name)
        if candidate_size is None:
            mismatches.append(f"size_missing: 요청 크기 {request.size.amount}{request.size.family} 있음, 후보엔 크기 표기 없음")
        elif candidate_size.family != request.size.family:
            mismatches.append(
                f"size_unit_mismatch: 요청은 {request.size.family}, 후보는 {candidate_size.family}"
            )
        elif candidate_size != request.size:
            mismatches.append(
                f"size_mismatch: 요청 {request.size.amount}{request.size.family}, "
                f"후보 {candidate_size.amount}{candidate_size.family}"
            )

    return ComparisonResult(matches=not mismatches, mismatches=mismatches)


def resolve_brand_ambiguity_llm(candidate_name: str, requested_brand: str) -> dict:
    """brand_appears_in이 False를 반환했지만(정규화된 문자열로 못 찾음),
    실제로는 다른 표기(별칭/줄임말 등)로 같은 브랜드를 가리킬 수 있는 애매한
    경우에만 Unit 4/5가 **선택적으로** 호출하는 보조 함수. 결과는 참고용
    신호일 뿐이다.

    **중요 — 이후 Unit에서도 절대 희석하면 안 되는 원칙**: 이 함수가 무엇을
    반환하든, "사용자가 명시한 브랜드/제외 브랜드를 어겼는지"의 최종 게이트는
    항상 brand_appears_in(규칙)이다. 이 함수의 match=True를 근거로 brand_
    appears_in의 False 판정을 뒤집어 후보를 통과시키면 안 된다 — 그러면
    이 티켓이 원래 고치려던 문제("그럴듯한 이유로 조건 위반 후보를 조용히
    선택")가 이 함수를 통해 그대로 재발한다. 이 함수의 올바른 용도는 오직
    "사용자에게 되물을지(needs_clarification) / NOT_FOUND로 처리할지"를
    판단하는 보조 신호뿐이다.

    이번 Unit에서는 정의 + 개별 호출 검증만 한다(product_agent.py에 연결
    안 함 — 실제 연결은 Unit 4/5)."""
    from configs.llm_config import get_llm

    llm = get_llm("intent", temperature=0, retry_owner="application")
    prompt = (
        "다음 상품명이 요청한 브랜드와 같은 브랜드(또는 그 브랜드의 다른 표기/별칭)를 "
        "가리키는지 판단하세요. 확실하지 않으면 match를 null로 두세요.\n\n"
        f'상품명: "{candidate_name}"\n요청 브랜드: "{requested_brand}"\n\n'
        'JSON으로만 답하세요: {"match": true|false|null, "confidence": 0.0~1.0, "reason": "한 문장"}'
    )
    try:
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        import json
        # 코드블록으로 감싸져 오는 경우 방어적으로 벗김
        cleaned = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)
        return {
            "match": parsed.get("match"),
            "confidence": float(parsed.get("confidence", 0.0)),
            "reason": str(parsed.get("reason", "")),
        }
    except Exception as e:
        return {"match": None, "confidence": 0.0, "reason": f"판단 실패: {type(e).__name__}"}
