"""발화 scope / goal_shift 공용 분류기 — WON-20 Unit 1.

"이 발화가 쇼핑과 관련 있는지"(scope)와 "목적이 바뀌었는지"(goal_shift)를 한 곳에서
판단한다. WON-38 의 classify_payment_question 과 같은 패턴 — 판단 로직을 한 함수에
모아 이후 intent_agent(Unit 2)와 fallback_orchestrator(Unit 3)가 공유한다.

    classify_scope(text, context) -> {"scope": ..., "goal_shift": ...}

    scope      : "in_scope" | "bridgeable" | "out_of_scope"
    goal_shift : bool   (out_of_scope 일 때만 True)

3단계 정의
  - in_scope     : 상품탐색/장바구니/결제/배송/주소 등 기존 쇼핑 흐름. goal_shift=False
  - bridgeable   : 이사·집들이·건강·외로움 등 쇼핑 추천으로 자연스럽게 이어질 수 있는
                   생활/감정 얘기("아이고 힘드네", "손주가 보고 싶네"). goal_shift=False
                   — 쇼핑 문맥을 유지한다.
  - out_of_scope : 가전 제어("TV 꺼줘"), 전화("아들한테 전화 걸어줘"), 법률/금융 상담,
                   부동산 지역 비교 등 쇼핑과 명백히 무관한 요청. goal_shift=True

설계 원칙 — Phase 1 은 보수적으로
  - high-confidence out_of_scope 만 명확히 잡는다. 애매하면 in_scope 로 기본값 —
    WON-39 실측에서 "잘못된 리셋(FP) 0건" 이었던 안전 상태를 깨지 않는다.
  - 규칙(키워드)만으로 시작한다. 별도 분류기(BERT 등)는 이 규모에서 불필요.
    borderline in_scope/bridgeable 를 LLM 으로 더 정교하게 가르는 건 후속 유닛의
    배선 몫이며, 그 seam 으로 context 인자를 받아 둔다(Phase 1 로직엔 미사용).
  - 이 함수는 scope/goal_shift 만 판단하고 "어떻게 응답할지"(행동)는 정하지 않는다.
    분류와 행동을 섞지 않는 게 핵심 — Unit 3 에서 다룰 배선 버그가 정확히 그 둘을
    뒤섞어서 생긴 것이었다.

이 유닛은 함수 정의만 한다 — 아직 어떤 노드도 이걸 쓰지 않는다.
"""
from __future__ import annotations

from typing import Optional, TypedDict


class ScopeResult(TypedDict):
    scope: str        # "in_scope" | "bridgeable" | "out_of_scope"
    goal_shift: bool


# ── out_of_scope 규칙 (high-confidence 만) ─────────────────────────────

# (1) 가전/기기 제어 — 기기 '명사' + 제어 '동사'가 함께 있을 때만.
#     명사만 있으면("TV 받침대 사줘") 쇼핑일 수 있으므로 잡지 않는다(보수적).
_DEVICE_NOUNS: tuple[str, ...] = (
    "tv", "티비", "티브이", "텔레비전", "라디오", "에어컨", "에어콘", "보일러",
    "히터", "난로", "선풍기", "공기청정기", "가습기", "제습기", "청소기", "세탁기",
    "전등", "형광등", "조명", "스탠드", "불", "인터넷", "와이파이", "wifi",
    "공유기", "채널", "볼륨", "소리",
)
_CONTROL_VERBS: tuple[str, ...] = (
    "꺼", "켜", "틀어", "끄지", "켜지", "줄여", "줄이", "높여", "낮춰", "낮추",
    "올려", "키워", "밝게", "어둡게", "돌려",
)

# (2) 전화/연락 — 연락 '명사' + 걸기/보내기 '동사'.
_CALL_MARKERS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("전화", "통화"), ("걸어", "걸으", "해줘", "해 줘", "연결", "하고 싶", "하게")),
    (("문자", "카톡", "톡", "메시지", "메세지", "문자메시지"), ("보내", "보낼", "전송", "쳐줘", "써줘")),
)

# (3) 법률/금융/부동산 상담·비교 — 이 어휘가 나오면 쇼핑 흐름이 아니다.
_FINANCE_LEGAL_REALESTATE: tuple[str, ...] = (
    "전세", "월세", "보증금", "전셋집", "임대차", "등기", "부동산", "매매가",
    "시세", "분양", "청약", "재개발", "재건축",
    "대출", "이자율", "금리", "주식", "펀드", "적금", "예금 금리",
    "보험금", "상속", "증여", "소송", "고소", "변호사", "법률 상담", "합의금", "위자료",
)


def _looks_out_of_scope(t: str) -> bool:
    low = t.lower()
    if any(n in low for n in _DEVICE_NOUNS) and any(v in t for v in _CONTROL_VERBS):
        return True
    for nouns, verbs in _CALL_MARKERS:
        if any(n in t for n in nouns) and any(v in t for v in verbs):
            return True
    if any(kw in t for kw in _FINANCE_LEGAL_REALESTATE):
        return True
    return False


# ── in_scope 규칙 (쇼핑 지시/조작 표현) ───────────────────────────────
# bridgeable 판정보다 먼저 소진한다: 쇼핑 발화가 생활 단어를 품어도
# ("무릎 보호대 다른 거 보여줘" 의 "무릎") in_scope 를 유지하기 위함.
_SHOPPING_MARKERS: tuple[str, ...] = (
    "담아", "장바구니", "카트", "결제", "주문", "구매", "사줘", "살래", "살게",
    "보여줘", "보여줄", "보여봐", "다시 보여", "다른 거", "다른거", "딴 거", "딴거",
    "그거", "그것", "저거", "이거", "이건", "요거", "아까", "방금", "그 상품", "그 제품",
    "더 싼", "더 비싼", "더 저렴", "더 큰", "더 작은", "더 많이", "더 적게",
    "몇 개", "얼마", "가격", "배송", "취소", "환불", "옵션", "번째",
)


# ── bridgeable 규칙 (생활/감정 스몰토크) ──────────────────────────────
_BRIDGEABLE_MARKERS: tuple[str, ...] = (
    # 감탄/감정
    "아이고", "아이구", "아이쿠", "에휴", "하이고", "아유", "허허",
    "힘드", "힘들", "피곤", "지치", "지쳐", "고단", "고달",
    "외롭", "적적", "쓸쓸", "심심", "혼자", "울적",
    "보고 싶", "보고싶", "그립", "그리워",
    # 가족
    "손주", "손자", "손녀", "며느리", "사위", "자식", "애들", "자녀", "영감",
    "명절", "설날", "추석", "제사", "차례",
    # 날씨/계절
    "날씨", "덥다", "더워", "무덥", "찜통", "춥다", "추워", "쌀쌀", "으슬", "선선",
    "비 와", "비가 와", "비 온다", "눈 와", "눈이 와", "미세먼지", "황사", "장마",
    # 건강/몸
    "무릎", "허리", "어깨", "관절", "삭신", "기력", "밥맛", "입맛", "속이",
    "아파", "아프", "쑤셔", "결려", "저려",
    "잠이 안", "잠이 통", "잠을 못", "불면", "뒤척",
    # 삶
    "세월", "나이 드니", "나이가 드니", "늙으니", "나이를 먹으니",
)


def classify_scope(text: str, context: Optional[dict] = None) -> ScopeResult:
    """발화의 scope 3단계와 goal_shift 를 판단한다. 행동은 정하지 않는다.

    context: 후속 유닛이 borderline 판정을 정교화(예: 현재 stage, 최근 keywords)할
    seam. Phase 1 로직에서는 참조하지 않는다 — 넘겨도 생략해도 결과가 같다.
    """
    t = (text or "").strip()
    if not t:
        return {"scope": "in_scope", "goal_shift": False}

    if _looks_out_of_scope(t):
        return {"scope": "out_of_scope", "goal_shift": True}

    if any(kw in t for kw in _SHOPPING_MARKERS):
        return {"scope": "in_scope", "goal_shift": False}

    if any(kw in t for kw in _BRIDGEABLE_MARKERS):
        return {"scope": "bridgeable", "goal_shift": False}

    # 애매하면 in_scope — Phase 1 보수적 기본값(오리셋 방지).
    return {"scope": "in_scope", "goal_shift": False}
