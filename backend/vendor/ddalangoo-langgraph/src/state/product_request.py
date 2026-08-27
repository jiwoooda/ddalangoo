"""ProductRequest — 사용자가 요청한 "특정 상품"을 카테고리/브랜드/제품명/옵션
단위로 구조화한 계약(WON-20 Unit 1).

지금까지 상품 검색 요청은 `keywords: list[str]` 하나로만 표현됐다 — "카테고리
검색"("우유 사줘")과 "정확한 제품 지정"("서울우유 나100% 1L 사줘")을 구분할 수
없고, `product_agent._matches_requested_keywords`가 keywords 중 하나만
일치해도(OR) 통과시키는 이유도 이 구분이 아예 없기 때문이다.

이 파일은 계약(모델)만 정의한다 — 아직 아무도 이 모델을 채우거나(Unit 2가
intent_agent에서 채움) 소비하지 않는다(Unit 4+가 product_agent에서 소비함).
기존 keywords 기반 검색/랭킹 로직은 이번 Unit에서 전혀 건드리지 않는다.

ShoppingState에는 Pydantic 인스턴스가 아니라 `.model_dump()`한 plain dict로
저장한다 — LangGraph state 전체가 체크포인터로 직렬화되는데, 이 프로젝트의
다른 구조화 출력(예: intent_agent.py의 CartOperation)도 전부 이 패턴을
따른다(파싱 시점에만 Pydantic, state에는 dict)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

MatchMode = Literal["category", "brand", "exact_product"]


class ProductRequest(BaseModel):
    category: Optional[str] = None
    brand: Optional[str] = None
    product_name: Optional[str] = None
    variant: Optional[str] = None
    size: Optional[str] = None
    quantity: Optional[int] = None
    platform: Optional[str] = None
    excluded_brands: list[str] = Field(default_factory=list)
    condition: Optional[str] = None
    # match_mode: 사용자가 얼마나 구체적으로 지정했는지.
    #   "category"      — "우유 사줘"(카테고리만)
    #   "brand"         — "서울우유 사줘"(브랜드까지)
    #   "exact_product" — "서울우유 나100% 1L 사줘"(제품 라인/옵션까지 특정)
    # exact_product인데 그 조건을 전부 만족하는 후보가 없으면(Unit 4/5) 다른
    # SKU로 조용히 대체하면 안 되고 NOT_FOUND/clarification으로 이어져야 한다.
    match_mode: MatchMode = "category"
    # 후보가 없을 때 조건을 완화해서라도(다른 브랜드/사이즈) 찾아봐도 되는지.
    # 기본은 False — 사용자가 명시적으로 동의한 뒤에만(Unit 7 대체품 동의
    # 플로우) True로 바뀐다. 자동으로 켜지면 안 된다.
    allow_substitution: bool = False
