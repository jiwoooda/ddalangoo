"""
Priority Resolver — Stage0(Context Agent)과 Stage3(필터) 사이의 순수 함수.

새 LLM 콜도, 새 그래프 노드도 아니다. Context Agent가 뽑은 routed_signals를
이번 Intent 기준으로 재판정해서, 과거에 명시적으로 배제했던 대상을 이번
요청이 다시 명시적으로 요청하면 그 배제를 무효화한다.
(예: 예전에 "나이키 싫음" → 이번엔 "나이키 운동화 추천해줘" → 배제 해제)

규칙:
  - safety(tier1)는 이 함수의 관여 대상이 아니다 — profile에서 항상 그대로
    통과한다 (build_preference_context에서 별도로 처리, override 불가).
  - explicit_exclusion(tier2): 이번 keywords에 같은 대상이 다시 명시되면
    무효화, 아니면 그대로 유효.
  - soft_preference(tier3): 배제하지 않고 그대로 통과하되, recency 순으로
    정렬해서 넘긴다 (rank_by_recency). 실제 배치/충돌 판정은 Stage4가
    LLM으로 한다 — 여기서는 "어느 게 더 최근인가"만 순서로 표현한다.
"""
from typing import Any

from src.state.routed_signal import RoutedSignal

# 카테고리 우선순위 — source가 다른 신호끼리 timestamp 없이 비교할 때 쓴다.
# session_smalltalk가 항상 general_context/purchase_history보다 최근으로
# 취급된다 ("이번 세션 발화가 더 최신 정보" 정책).
_SOURCE_RECENCY_RANK = {"session_smalltalk": 2, "purchase_history": 1, "general_context": 0}


def _mentions_same_target(keyword: str, signal_value: str) -> bool:
    a, b = keyword.lower().strip(), signal_value.lower().strip()
    return bool(a) and bool(b) and (a in b or b in a)


def _recency_sort_key(signal: RoutedSignal, index: int) -> tuple:
    """
    값이 클수록 더 최근으로 취급한다. 카테고리 순위(_SOURCE_RECENCY_RANK)가
    항상 1순위 기준이다 — session_smalltalk는 구매이력이 아무리 최근이어도
    카테고리 규칙("세션이 항상 우선")에 따라 그걸 이긴다. purchase_history의
    실제 timestamp는 같은 카테고리(purchase_history끼리) 안에서만 비교에
    쓰인다. 그 외(같은 카테고리의 general_context/session_smalltalk끼리)는
    routed_signals 리스트에 등장한 순서로 tie-break한다 —
    CONTEXT_CLASSIFICATION_PROMPT가 발화 등장 순서를 유지해서 신호를
    내놓도록 지시하므로, 리스트의 뒷쪽일수록 더 최근 발화다.
    """
    category = _SOURCE_RECENCY_RANK.get(signal.source, 0)
    if signal.source == "purchase_history" and signal.timestamp:
        return (category, signal.timestamp, index)
    return (category, "", index)


def rank_by_recency(signals: list[RoutedSignal]) -> list[RoutedSignal]:
    """가장 최근(우선순위 높음) 신호가 앞에 오도록 정렬한 새 리스트를 반환한다."""
    indexed = list(enumerate(signals))
    indexed.sort(key=lambda pair: _recency_sort_key(pair[1], pair[0]), reverse=True)
    return [s for _, s in indexed]


def resolve_precedence(keywords: list[str], routed_signals: list[RoutedSignal]) -> dict[str, Any]:
    effective_exclusions: list[RoutedSignal] = []
    overridden_exclusions: list[RoutedSignal] = []
    active_soft_preferences: list[RoutedSignal] = []
    retrieval_signals: list[RoutedSignal] = []

    for signal in routed_signals:
        if signal.decision_role == "explicit_exclusion":
            if any(_mentions_same_target(kw, signal.value) for kw in keywords):
                overridden_exclusions.append(signal)
            else:
                effective_exclusions.append(signal)
        elif signal.decision_role == "soft_preference":
            active_soft_preferences.append(signal)
        elif signal.decision_role == "retrieval":
            retrieval_signals.append(signal)

    return {
        "effective_exclusions": effective_exclusions,
        "active_soft_preferences": rank_by_recency(active_soft_preferences),
        "retrieval_signals": retrieval_signals,
        "overridden_exclusions": overridden_exclusions,
    }
