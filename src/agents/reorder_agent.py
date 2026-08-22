"""
Reorder Agent Node.

역할:
  1. 구매이력에서 재구매 후보 탐색 (실제 DB)
  2. URL 검증 + 후보 선택
  3. product_confirming 또는 product_agent(no_match)로 직접 반환

기존 memory_agent(reorder 분기) + reorder_node 통합.

[미구현 — 설계 vs 현재 구현 괴리]
원래 설계는 (1) product_name/keyword/category/brand/option_text 가중치
매칭 + 최근성 + 만족도로 점수를 매기는 `_score_history`, (2) 상위 두 후보
점수가 근접할 때만 LLM으로 재랭킹하는 `_rerank_with_llm`(confidence 임계값
0.75) 두 단계였다. 지금은 둘 다 구현 안 돼 있고:
  - 모든 후보의 score를 0.8로 하드코딩 (`_resolve_reorder_candidates` 참고)
  - 후보가 2개 이상이면 무조건 사용자에게 되물음 (LLM 재랭킹 없음)
당장 동작에는 문제없지만(사용자가 직접 고르므로), 재구매 정확도를 높이려면
이 설계대로 구현하는 작업이 남아있다.
"""
from typing import Any
from src.state.schema import ShoppingState
from src.state.node_inputs import ReorderAgentInput, ReorderAgentUpdate
from src.tools import db_client
from src.utils.agent_logger import agent_logger


# ── DB 접근은 전부 db_client(mock/real 모드 전환)를 경유한다 ────────────

def _fetch_histories_by_keywords(
    user_id: str,
    keywords: list[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    result = db_client.get_purchase_histories_by_keywords(user_id, keywords, limit)
    agent_logger.log(f"[reorder_agent] 키워드 구매이력: {len(result)}건 (keywords={keywords})")
    return result


def _validate_product_url(url: str) -> bool:
    """실제 쇼핑몰 URL 유효성 검증."""
    return db_client.validate_product_url(url)


# ── 후보 안내 문구 ──────────────────────────────────────────────
# 목록 자체(상품명)는 실제 구매이력이라 정확해야 하므로 LLM이 아니라 코드가
# 그대로 조립한다 — 말투만 친근하게 다듬은 고정 템플릿(사용자 확인 완료,
# fl-2026-08-21-002 재질문 케이스). LLM에 자유 생성을 맡기면 상품명이
# 바뀌거나 누락될 위험(할루시네이션)이 있어 어르신 대상 서비스에선 부적절.

def _format_candidate_names(candidates: list[dict]) -> str:
    return ", ".join(
        f"{i+1}. {c.get('product_name', '상품')}"
        for i, c in enumerate(candidates[:3])
    )


def _ambiguous_question(candidates: list[dict]) -> str:
    names = _format_candidate_names(candidates)
    return (
        f"저번에 이런 걸 사셨어요: {names}. "
        "이 중에 찾으시는 게 있으실까요? 다른 상품이면 조금 더 자세히 "
        "말씀해주시면 제가 더 잘 찾아드릴게요!"
    )


def _ambiguous_next_batch_question(candidates: list[dict]) -> str:
    """직전에 보여준 후보를 사용자가 못 알아봤을 때(select 실패) 쓴다. 같은
    목록을 그대로 반복하면 사용자가 이미 "모르겠다"고 한 걸 다시 들이미는
    셈이라(사용자 확인) — 구매이력 중 아직 안 보여준 다른 후보가 있으면
    그걸 대신 보여준다."""
    names = _format_candidate_names(candidates)
    return f"그럼 다른 것도 보여드릴게요: {names}. 혹시 이 중에 있으실까요?"


def _ambiguous_no_more_candidates_message() -> str:
    """select 실패했는데 더 보여줄 구매이력도 안 남았을 때 — 목록을 반복하는
    대신 상품을 더 구체적으로 설명해달라고 요청으로 전환한다."""
    return "음, 예전에 사셨던 건 그게 다예요. 어떤 상품을 찾으시는지 조금 더 자세히 말씀해주시면 제가 더 잘 찾아드릴게요!"


# ── 후보 탐색 로직 ──────────────────────────────────────────────

def _get_latest_user_text(state: ShoppingState) -> str:
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, dict):
            content = msg.get("content")
            role = msg.get("role") or msg.get("type")
            if content and role in (None, "user", "human"):
                return str(content)
        else:
            content = getattr(msg, "content", None)
            msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
            if content and msg_type in (None, "human", "user"):
                return str(content)
    return ""


def _resolve_reorder_candidates(
    user_id: str,
    keywords: list[str],
    query: str,
    top_k: int = 5,
) -> dict[str, Any]:
    if keywords:
        history = _fetch_histories_by_keywords(user_id, keywords, limit=top_k)
    else:
        # 상품명이 아예 없으면(keywords=[]) 원문 문장을 검색어로 쓰지 않는다 —
        # "저번에 샀던 거 다시 사줘" 같은 문장은 실제 상품명과 절대 안 겹쳐서
        # 항상 no_match로 새고, 구매이력이 실제로 있어도 없다고 나온다(실측
        # 확인, fl-2026-08-21-001). 이 경우는 키워드로 좁히는 대신 최근
        # 구매이력을 그대로 가져온다 — 2개 이상이면 아래 ambiguous 분기가
        # 그대로 "어떤 걸로 할까요?"로 되물어준다.
        history = db_client.get_purchase_histories(user_id)[:top_k]
        agent_logger.log(f"[reorder_agent] keywords 없음 -> 최근 구매이력 {len(history)}건으로 대체")

    candidates = []
    for item in history:
        candidates.append({
            "purchase_history_id": item.get("id"),
            "product_id": item.get("product_id"),
            "product_option_id": item.get("product_option_id"),
            "product_name": item.get("product_name"),
            "product_url": item.get("product_url"),
            "option_text": item.get("option_text"),
            "selected_options": item.get("selected_options") or {},
            "price_at_purchase": item.get("price_at_purchase", 0),
            "platform": item.get("platform"),
            "purchased_at": item.get("purchased_at"),
            # 하드코딩 — 설계했던 _score_history(가중치 매칭+최근성+만족도)
            # 미구현 상태라 전부 동일 점수. 모듈 docstring의 "미구현" 참고.
            "score": 0.8,
        })

    if not candidates:
        return {"resolution_type": "no_match", "candidates": []}

    candidates.sort(key=lambda c: c.get("purchased_at") or "", reverse=True)

    seen_names: set[str] = set()
    distinct: list[dict] = []
    for c in candidates:
        name = (c.get("product_name") or "").strip()
        if name not in seen_names:
            seen_names.add(name)
            distinct.append(c)

    # 설계했던 _rerank_with_llm(상위 두 후보 점수가 근접할 때만 LLM으로
    # 재랭킹, confidence 0.75 임계값)이 미구현이라, 후보가 2개 이상이면
    # 점수 차이와 무관하게 항상 사용자에게 되묻는다.
    if len(distinct) >= 2:
        shown, remaining = distinct[:3], distinct[3:]
        return {
            "resolution_type": "ambiguous",
            "candidates": shown,
            # 처음엔 top_k(최대 3개)만 보여주고, 나머지는 select 실패 시
            # 다음 후보로 꺼내 쓸 수 있게 남겨둔다.
            "remaining_candidates": remaining,
            "question": _ambiguous_question(shown),
        }

    return {"resolution_type": "resolved", "candidates": candidates, "selected": candidates[0]}


def _confirm_candidate(candidate: dict) -> dict:
    raw_url = candidate.get("product_url", "")
    product_url = raw_url if _validate_product_url(raw_url) else ""
    price = candidate.get("price_at_purchase", candidate.get("price", 0))
    product_name = candidate.get("product_name", "상품")
    selected_product = {
        "product_id": candidate.get("product_id"),
        "product_option_id": candidate.get("product_option_id"),
        "purchase_history_id": candidate.get("purchase_history_id"),
        "product_name": product_name,
        "brand": candidate.get("brand"),
        "category": candidate.get("category"),
        "price": price,
        "platform": candidate.get("platform", ""),
        "option_text": candidate.get("option_text"),
        "selected_options": candidate.get("selected_options") or {},
        "product_url": product_url,
    }
    return {
        "selected_product": selected_product,
        "product_url": product_url,
        "pending_action": {
            "type": "product_confirm",
            "message": f"{product_name}, {price:,}원이에요. 이번에도 다시 주문할까요?",
            "payload": {
                "purchase_history_id": candidate.get("purchase_history_id"),
                "product_url": product_url,
                "selected_options": candidate.get("selected_options") or {},
                "option_text": candidate.get("option_text"),
            },
        },
        "stage": "product_confirming",
        "error": None,
        "last_agent": "reorder_agent",
    }


def _selection_terms(text: str, keywords: list[str]) -> list[str]:
    base = f"{text} {' '.join(keywords or [])}".lower().replace(" ", "")
    terms = [base] if base else []
    aliases = {
        "딸기": ["strawberry"],
        "신선": ["fresh"],
        "냉동": ["frozen"],
        "설향": ["설향"],
    }
    for key, values in aliases.items():
        if key in base:
            terms.extend(values)
    seen = set()
    return [t for t in terms if t and not (t in seen or seen.add(t))]


def _candidate_text(candidate: dict) -> str:
    return " ".join(
        str(candidate.get(field) or "")
        for field in ("product_name", "option_text", "brand", "category", "keyword")
    ).lower().replace(" ", "")


def _select_from_pending(state: ShoppingState) -> dict | None:
    pending = state.get("pending_action") or {}
    candidates = (pending.get("payload") or {}).get("candidates") or []
    if not candidates:
        return None

    user_text = _get_latest_user_text(state)
    digits = [ch for ch in user_text if ch.isdigit()]
    if digits:
        index = int(digits[0]) - 1
        if 0 <= index < len(candidates):
            return candidates[index]

    terms = _selection_terms(user_text, state.get("keywords") or [])
    scored = sorted(
        [(sum(1 for t in terms if t in _candidate_text(c)), c) for c in candidates],
        key=lambda x: x[0],
        reverse=True,
    )
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


# ── 메인 노드 ────────────────────────────────────────────────────

def reorder_agent_node(state: ReorderAgentInput) -> ReorderAgentUpdate:
    """
    Reorder Agent.

    [product_select pending]  사용자가 모호한 후보 중 선택 → 확인 단계로
    [새 reorder 요청]          구매이력 탐색 → resolved/ambiguous/no_match 처리
    """
    pending = state.get("pending_action") or {}
    user_id = state.get("user_id", "")
    keywords = state.get("keywords") or []

    agent_logger.log(
        f"\n{'─'*40}\n[reorder_agent] 진입 | pending_type={pending.get('type')}  "
        f"user_id={user_id}  keywords={keywords}\n{'─'*40}"
    )

    # 사용자가 모호한 후보 목록에서 선택하는 경우
    if pending.get("type") == "product_select":
        candidate = _select_from_pending(state)
        if candidate:
            agent_logger.log(f"[reorder_agent] product_select → 후보 선택됨: {candidate.get('product_name')}")
            output = _confirm_candidate(candidate)
            agent_logger.log_reorder_agent(
                {"pending_type": "product_select", "user_id": user_id, "keywords": keywords},
                {"resolution_type": "resolved", "selected_candidate": candidate,
                 "candidates": (pending.get("payload") or {}).get("candidates") or [],
                 "stage": output.get("stage"), "pending_action": output.get("pending_action")},
            )
            return output
        # 같은 후보 목록을 그대로 다시 보여주면, 사용자가 이미 "모르겠다"고
        # 답한 걸 또 들이미는 셈이다(사용자 확인, fl-2026-08-21-002 후속).
        # 구매이력 중 아직 안 보여준 다른 후보가 있으면 그걸 꺼내 보여주고,
        # 더 없으면 목록 반복 대신 구체적인 설명을 요청하는 쪽으로 전환한다.
        remaining = (pending.get("payload") or {}).get("remaining_candidates") or []
        if remaining:
            next_batch, new_remaining = remaining[:3], remaining[3:]
            output = {
                "pending_action": {
                    "type": "product_select",
                    "message": _ambiguous_next_batch_question(next_batch),
                    "payload": {"candidates": next_batch, "remaining_candidates": new_remaining},
                },
                "stage": "product_confirming",
                "error": None,
                "last_agent": "reorder_agent",
            }
        else:
            # 더 보여줄 구매이력이 없다 — product_select를 계속 유지하면 다음
            # 턴에 사용자가 완전히 새 상품명을 말해도 라우터가 reorder_agent/
            # respond 사이에서만 맴돌고 product_agent로 못 간다(_route_product_
            # confirming의 product_select 분기는 buy intent를 respond로 보냄).
            # pending_action을 비우고 stage를 idle로 되돌려 다음 턴을 완전히
            # 새 구매 요청처럼 처리되게 한다. needs_clarification/clarification_
            # reason도 여기서 명시적으로 꺼야 respond_node가 intent_agent의
            # 오래된 일반 문구 대신 이 안내를 쓴다(fl-2026-08-21-002와 같은
            # 우선순위 문제 재발 방지).
            output = {
                "pending_action": None,
                "stage": "idle",
                "error": None,
                "last_agent": "reorder_agent",
                "needs_clarification": False,
                "clarification_reason": None,
                "immediate_response": _ambiguous_no_more_candidates_message(),
            }
        agent_logger.log_reorder_agent(
            {"pending_type": "product_select", "user_id": user_id, "keywords": keywords},
            {"resolution_type": "select_failed", "candidates": [],
             "stage": output.get("stage"), "pending_action": output.get("pending_action")},
        )
        return output

    # 새 reorder 요청: 구매이력 탐색
    query = _get_latest_user_text(state) or " ".join(keywords)
    result = _resolve_reorder_candidates(user_id, keywords, query)
    resolution_type = result["resolution_type"]

    if resolution_type == "no_match":
        output = {
            "stage": "searching",
            "error": "reorder_no_match",
            "search_results": [],
            "last_agent": "reorder_agent",
        }
        agent_logger.log_reorder_agent(
            {"pending_type": pending.get("type", "-"), "user_id": user_id, "keywords": keywords},
            {**result, "stage": output.get("stage"), "pending_action": None},
        )
        return output

    if resolution_type == "ambiguous":
        candidates = result["candidates"]
        output = {
            "pending_action": {
                "type": "product_select",
                "message": result.get("question", "이전에 사신 상품이 여러 개예요. 어떤 걸로 할까요?"),
                "payload": {
                    "candidates": candidates,
                    "remaining_candidates": result.get("remaining_candidates") or [],
                },
            },
            "stage": "product_confirming",
            "error": None,
            "search_results": [],
            "last_agent": "reorder_agent",
        }
        agent_logger.log_reorder_agent(
            {"pending_type": pending.get("type", "-"), "user_id": user_id, "keywords": keywords},
            {**result, "stage": output.get("stage"), "pending_action": output.get("pending_action")},
        )
        return output

    # resolved
    output = _confirm_candidate(result["selected"])
    agent_logger.log_reorder_agent(
        {"pending_type": pending.get("type", "-"), "user_id": user_id, "keywords": keywords},
        {**result, "selected_candidate": result["selected"],
         "stage": output.get("stage"), "pending_action": output.get("pending_action")},
    )
    return output
