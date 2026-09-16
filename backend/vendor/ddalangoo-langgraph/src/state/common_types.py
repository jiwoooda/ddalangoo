"""Cycle-free workflow literals shared by state and recovery contracts."""
from typing import Literal, TypeAlias


Stage: TypeAlias = Literal[
    "idle",
    "searching",
    "product_confirming",
    "cart_shopping",
    "recipe_planning",
    "payment_processing",
    "payment_password_required",
    "completed",
    "failed",
]

Intent: TypeAlias = Literal[
    "buy",
    "reorder",
    "confirm",
    "deny",
    "next",
    "refine",
    "compare_platforms",
    "quantity_change",
    "address_change",
    "option_select",
    "ask",
    # WON-23 Unit 1 — 아직 상품을 정하기 전, "어떤 게 나을지" 조언을 구하는
    # 발화("사과랑 딸기 중 뭐가 나아?", "이 계절엔 뭐가 맛있어?"). ask(이미
    # 고른 상품에 대한 질문)와는 대상이 다르고, next(다른 후보 요청, 진행
    # 중인 검색이 있어야 함)와도 다르다 — 카탈로그 접근 없이 조언만 생성
    # (분류·라우팅은 Unit 2/3, 이번 Unit은 분류값만 추가).
    "product_decision_advice",
    "cancel",
    "unclear",
]
