"""결제 흐름 질문의 (topic, type) 공용 분류기 — WON-38 Unit 1.

지금까지 결제 질문 응답은 "키워드 하나 → 정해진 fact 하나"의 flat 매칭이라
(1) substring 충돌로 오답("배송지"가 "배송"에 걸려 배송 안내), (2) 질문 유형
(무엇인지 / 어떻게 하는지 / 어디서 하는지)을 아예 안 뽑아서 새 유형마다 빈틈이
생겼다(WON-38 조사). 그 두 축을 한 번에 판단한다:

    classify_payment_question(text) -> {"topic": ..., "type": ...}

    topic: "payment_method" | "delivery" | "cancel" | "address" | None
    type : "what" | "procedure" | None   (topic 이 None 이면 type 도 None)

이 유닛은 함수 정의만 한다 — 아직 어떤 노드도 이걸 쓰지 않는다(Unit 2~4에서 배선).
기존 4개 키워드 그룹(payment/node.py 의 _PAYMENT_METHOD_QUESTION_KEYWORDS /
_DELIVERY_QUESTION_KEYWORDS / _CANCEL_QUESTION_KEYWORDS, response_agent.py 의
_ADDRESS_KEYWORDS)을 여기로 통합한다. 중복 제거(intent_agent.py 의 라우팅 게이트
_PAYMENT_QUESTION_KEYWORDS 등)는 Unit 2 이후.
"""
from __future__ import annotations

from typing import Optional, TypedDict


class PaymentQuestion(TypedDict):
    topic: Optional[str]  # "payment_method" | "delivery" | "cancel" | "address" | None
    type: Optional[str]   # "what" | "procedure" | None


# topic 우선순위 순서대로 검사한다: 취소 > 주소 > 배송 > 결제수단.
#  - 취소 우선: "취소하면 배송은 어떻게 돼요?" 같은 복합 발화에서 확정 전 취소
#    안내가 우선(기존 WON-35 Unit 3 동작 유지).
#  - 주소를 배송보다 앞: "배송지"가 "배송"(substring)에 걸려 delivery 로 오매칭되던
#    문제(WON-38 조사 #10) — address 그룹을 먼저 소진해 "배송지/배달 주소"류를 먼저 잡는다.
_TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cancel", ("취소",)),
    ("address", (
        "배송지", "주소", "배달지", "배달 주소", "받는 곳", "받는곳", "받는 사람", "수령지", "수령 주소",
    )),
    ("delivery", ("배송", "도착", "택배", "배달")),
    ("payment_method", (
        "결제수단", "결제 수단", "결제방법", "결제 방법", "결제", "카드",
        "무통장", "계좌이체", "페이", "네이버페이",
        # open-vocabulary 보강 (WON-38 조사 #5 "돈은 어떻게 치러야…"). 뻔한 동의어만,
        # 무한 확장 금지.
        "돈", "치러", "치르", "지불",
    )),
)

# "무엇인지"가 아니라 "어떻게/어디서 하는지"를 묻는 표시어.
_PROCEDURE_MARKERS: tuple[str, ...] = (
    "어떻게", "어디서", "어디다", "어디에", "어디", "방법", "절차",
    "등록", "신청", "가입", "입력", "적어", "적나", "기재", "바꿔", "바꾸", "변경",
)


def classify_payment_question(text: str) -> PaymentQuestion:
    t = (text or "").strip()
    if not t:
        return {"topic": None, "type": None}

    topic: Optional[str] = None
    for cand_topic, keywords in _TOPIC_KEYWORDS:
        if any(kw in t for kw in keywords):
            topic = cand_topic
            break

    if topic is None:
        return {"topic": None, "type": None}

    if topic == "cancel":
        # 취소엔 "절차 안내" 개념이 없다 — 확정 전이면 "지금 말씀하시면 취소 가능"
        # (WON-35), 확정 후 취소·환불은 범위 밖(WON-36). 항상 what.
        return {"topic": "cancel", "type": "what"}

    q_type = "procedure" if any(m in t for m in _PROCEDURE_MARKERS) else "what"
    return {"topic": topic, "type": q_type}
