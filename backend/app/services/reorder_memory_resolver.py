from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from app.repositories import purchase_history_repository


def _fetch_histories_from_db(user_id: int) -> list[dict[str, Any]] | None:
    """PostgreSQL에서 구매이력 조회. 실패 시 None 반환."""
    import asyncio

    async def _runner():
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from app.repositories.purchase_history_repository import get_histories_by_user_id_db

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            return None
        engine = create_async_engine(database_url, pool_pre_ping=True, pool_size=1, max_overflow=0)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
        try:
            async with factory() as session:
                return await get_histories_by_user_id_db(session, user_id)
        finally:
            await engine.dispose()

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_runner())
        finally:
            loop.close()
    except Exception:
        return None


def _get_histories(user_id: int) -> list[dict[str, Any]]:
    """DB 우선, 실패 시 mock JSON fallback."""
    result = _fetch_histories_from_db(user_id)
    if result is not None:
        return result
    return purchase_history_repository.get_histories_by_user_id(user_id)


RECENCY_WORDS = (
    "저번에",
    "전에",
    "이전에",
    "먹었던",
    "샀던",
    "지난번",
    "다시",
    "재구매",
    "last",
    "previous",
    "before",
)

AMBIGUOUS_SCORE_GAP = 0.08

KEYWORD_ALIASES = {
    "딸기": ["딸기", "strawberry"],
    "strawberry": ["strawberry", "딸기"],
    "참기름": ["참기름", "sesame_oil", "sesame"],
    "sesame_oil": ["sesame_oil", "참기름", "sesame"],
    "두유": ["두유", "soy_milk", "soy"],
    "soy_milk": ["soy_milk", "두유", "soy"],
    "달걀": ["달걀", "계란", "egg"],
    "계란": ["계란", "달걀", "egg"],
    "egg": ["egg", "달걀", "계란"],
    "두부": ["두부", "tofu"],
    "tofu": ["tofu", "두부"],
    "당근": ["당근", "carrot"],
    "carrot": ["carrot", "당근"],
    "브로콜리": ["브로콜리", "broccoli"],
    "broccoli": ["broccoli", "브로콜리"],
    "시금치": ["시금치", "spinach"],
    "spinach": ["spinach", "시금치"],
    "바나나": ["바나나", "banana"],
    "banana": ["banana", "바나나"],
    "만두": ["만두", "교자", "mandu"],
    "닭가슴살": ["닭가슴살", "chicken_breast"],
    "라면": ["라면", "ramyeon", "ramen"],
    "ramyeon": ["ramyeon", "라면"],
}


def resolve_reorder_memory(
    user_id: int,
    query: str,
    keywords: list[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    candidates = _search_candidates_sql(user_id, query, keywords or [], top_k)
    if not candidates:
        return _normalize_result(
            {
                "resolution_type": "no_match",
                "selected_purchase_history_id": None,
                "confidence": 0.0,
                "needs_user_selection": False,
                "candidate_ids": [],
                "reason": "no purchase history candidate matched",
            },
            candidates,
        )

    llm_result = _rerank_with_llm(query, keywords or [], candidates)
    validated = _validate_llm_result(llm_result, candidates)
    return _normalize_result(validated, candidates)


def _search_candidates_sql(
    user_id: int,
    query: str,
    keywords: list[str],
    top_k: int,
) -> list[dict[str, Any]]:
    histories = _get_histories(user_id)
    terms = _expand_terms(query, keywords)
    scored: list[dict[str, Any]] = []

    for history in histories:
        score, reasons = _score_history(history, query, terms)
        if score <= 0:
            continue

        candidate = _candidate_from_history(history)
        candidate["_rank_score"] = score
        candidate["score"] = round(min(score, 1.0), 3)
        candidate["base_score"] = candidate["score"]
        candidate["reason"] = " + ".join(reasons)
        scored.append(candidate)

    if len(scored) > 1 and any(word in query for word in RECENCY_WORDS):
        newest = max(_parse_datetime(item.get("purchased_at")) for item in scored)
        for item in scored:
            days_from_newest = max((newest - _parse_datetime(item.get("purchased_at"))).days, 0)
            if days_from_newest <= 7:
                bonus = 0.15
            elif days_from_newest <= 30:
                bonus = 0.10
            elif days_from_newest <= 90:
                bonus = 0.05
            else:
                bonus = 0.02
            item["_rank_score"] = (item.get("_rank_score") or item.get("score") or 0) + bonus
            item["score"] = round(min(item["_rank_score"], 1.0), 3)
            item["base_score"] = item["score"]

    scored.sort(
        key=lambda item: (
            item.get("_rank_score") or item.get("score") or 0,
            _parse_datetime(item.get("purchased_at")),
        ),
        reverse=True,
    )
    return scored[:top_k]


def _rerank_with_llm(
    user_query: str,
    keywords: list[str],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Use code for clear cases, and ask an LLM only for ambiguous top-k candidates."""
    if not candidates:
        return {
            "resolution_type": "no_match",
            "selected_purchase_history_id": None,
            "confidence": 0.0,
            "needs_user_selection": False,
            "candidate_ids": [],
            "reason": "no candidates",
        }

    ranked = sorted(
        candidates,
        key=lambda c: c.get("_rank_score") or c.get("score") or 0,
        reverse=True,
    )
    best = ranked[0]
    second_score = (
        ranked[1].get("_rank_score") or ranked[1].get("score", 0)
        if len(ranked) > 1
        else 0
    )
    best_score = best.get("_rank_score") or best.get("score") or 0

    if _prefers_recent_purchase(user_query):
        newest = max(ranked, key=lambda c: _parse_datetime(c.get("purchased_at")))
        return {
            "resolution_type": "resolved",
            "selected_purchase_history_id": newest["purchase_history_id"],
            "confidence": 0.9,
            "needs_user_selection": False,
            "candidate_ids": [newest["purchase_history_id"]],
            "reason": "user referred to a previous/recent purchase, so the latest matching purchase history was selected",
        }

    if len(ranked) > 1 and best_score - second_score < AMBIGUOUS_SCORE_GAP:
        llm_result = _rerank_ambiguous_candidates_with_llm(
            user_query=user_query,
            keywords=keywords,
            candidates=ranked[:5],
        )
        if llm_result:
            return llm_result
        return _ambiguous_result(ranked)

    return {
        "resolution_type": "resolved",
        "selected_purchase_history_id": best["purchase_history_id"],
        "confidence": min(max(best_score, 0.75), 1.0),
        "needs_user_selection": False,
        "candidate_ids": [best["purchase_history_id"]],
        "reason": best.get("reason") or "best matching purchase history candidate",
    }


def _ambiguous_result(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    best_score = candidates[0].get("_rank_score") or candidates[0].get("score") or 0
    return {
        "resolution_type": "ambiguous",
        "selected_purchase_history_id": None,
        "confidence": min(best_score, 1.0),
        "needs_user_selection": True,
        "candidate_ids": [c["purchase_history_id"] for c in candidates[:3]],
        "reason": "multiple purchase history candidates have similar scores",
    }


def _rerank_ambiguous_candidates_with_llm(
    user_query: str,
    keywords: list[str],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except Exception:
        return None

    public_candidates = [
        {
            "purchase_history_id": c.get("purchase_history_id"),
            "product_name": c.get("product_name"),
            "category": c.get("category"),
            "brand": c.get("brand"),
            "option_text": c.get("option_text"),
            "platform": c.get("platform"),
            "price_at_purchase": c.get("price_at_purchase"),
            "purchased_at": c.get("purchased_at"),
            "base_score": c.get("score"),
            "reason": c.get("reason"),
        }
        for c in candidates
    ]
    prompt = {
        "user_query": user_query,
        "keywords": keywords,
        "candidates": public_candidates,
        "output_schema": {
            "resolution_type": "resolved | ambiguous | no_match",
            "selected_purchase_history_id": "candidate id or null",
            "confidence": "0.0~1.0",
            "needs_user_selection": "boolean",
            "candidate_ids": "candidate ids to show when ambiguous",
            "question": "question to ask user when ambiguous",
            "reason": "short reason",
        },
    }

    system = (
        "You resolve ambiguous reorder requests using only the provided purchase "
        "history candidates. Never invent products or ids. Return JSON only. "
        "If confidence is below 0.75 or multiple candidates remain plausible, "
        "return ambiguous and ask the user to choose."
    )

    try:
        response = ChatOpenAI(model="gpt-4o-mini", temperature=0).invoke([
            SystemMessage(content=system),
            HumanMessage(content=json.dumps(prompt, ensure_ascii=False)),
        ])
        content = str(response.content).strip()
        if "```" in content:
            import re

            match = re.search(r"```(?:json)?\s*([\s\S]+?)```", content)
            if match:
                content = match.group(1).strip()
        parsed = json.loads(content)
    except Exception:
        return None

    if not isinstance(parsed, dict):
        return None
    return parsed


def _validate_llm_result(
    llm_result: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_ids = {c["purchase_history_id"] for c in candidates}
    resolution_type = llm_result.get("resolution_type")
    selected_id = llm_result.get("selected_purchase_history_id")
    confidence = float(llm_result.get("confidence") or 0)

    if resolution_type == "resolved":
        if selected_id not in candidate_ids:
            return {
                **llm_result,
                "resolution_type": "ambiguous" if candidates else "no_match",
                "selected_purchase_history_id": None,
                "needs_user_selection": bool(candidates),
                "candidate_ids": [c["purchase_history_id"] for c in candidates[:3]],
                "reason": "selected id was not in candidate list",
            }
        if confidence < 0.75:
            return {
                **llm_result,
                "resolution_type": "ambiguous",
                "selected_purchase_history_id": None,
                "needs_user_selection": True,
                "candidate_ids": [c["purchase_history_id"] for c in candidates[:3]],
                "reason": "confidence below threshold",
            }

    if resolution_type == "ambiguous":
        valid_ids = [
            candidate_id
            for candidate_id in (llm_result.get("candidate_ids") or [])
            if candidate_id in candidate_ids
        ]
        return {
            **llm_result,
            "selected_purchase_history_id": None,
            "needs_user_selection": True,
            "candidate_ids": valid_ids or [c["purchase_history_id"] for c in candidates[:3]],
        }

    if resolution_type not in {"resolved", "ambiguous", "no_match"}:
        return {
            "resolution_type": "ambiguous" if candidates else "no_match",
            "selected_purchase_history_id": None,
            "confidence": confidence,
            "needs_user_selection": bool(candidates),
            "candidate_ids": [c["purchase_history_id"] for c in candidates[:3]],
            "reason": "invalid resolution_type",
        }

    return llm_result


def _normalize_result(
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    public_candidates = [_strip_internal(candidate) for candidate in candidates]
    resolution_type = result.get("resolution_type")
    selected_id = result.get("selected_purchase_history_id")
    selected = next(
        (candidate for candidate in public_candidates if candidate["purchase_history_id"] == selected_id),
        None,
    )

    if resolution_type == "resolved" and selected is not None:
        return {
            "resolution_type": "resolved",
            "resolved": True,
            "needs_user_selection": False,
            "selected_candidate": {**selected, "reason": result.get("reason") or selected.get("reason")},
            "candidates": public_candidates,
        }

    if resolution_type == "ambiguous":
        candidate_ids = set(result.get("candidate_ids") or [])
        visible_candidates = [
            candidate for candidate in public_candidates
            if not candidate_ids or candidate["purchase_history_id"] in candidate_ids
        ][:3]
        return {
            "resolution_type": "ambiguous",
            "resolved": False,
            "needs_user_selection": True,
            "selected_candidate": None,
            "candidates": visible_candidates,
            "question": result.get("question") or _build_ambiguous_question(visible_candidates),
        }

    return {
        "resolution_type": "no_match",
        "resolved": False,
        "needs_user_selection": False,
        "selected_candidate": None,
        "candidates": [],
    }


def _strip_internal(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidate.items() if not key.startswith("_")}


def _prefers_recent_purchase(query: str) -> bool:
    return any(word in query for word in RECENCY_WORDS)


def _build_ambiguous_question(candidates: list[dict[str, Any]]) -> str:
    names = [
        str(candidate.get("product_name") or "").strip()
        for candidate in candidates
        if candidate.get("product_name")
    ]
    if not names:
        return "비슷한 구매 이력이 몇 가지 있어요. 어떤 상품으로 다시 주문할까요?"
    if len(names) == 1:
        return f"{names[0]}로 다시 주문할까요?"
    if len(names) == 2:
        return f"비슷한 구매 이력이 있어요. {names[0]}와 {names[1]} 중 어떤 걸로 다시 주문할까요?"
    head = ", ".join(names[:-1])
    return f"비슷한 구매 이력이 있어요. {head}, 그리고 {names[-1]} 중 어떤 걸로 다시 주문할까요?"


def _score_history(
    history: dict[str, Any],
    query: str,
    terms: list[str],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    weighted_fields = [
        ("product_name", 0.35),
        ("keyword", 0.30),
        ("category", 0.15),
        ("brand", 0.10),
        ("option_text", 0.05),
    ]

    for field, weight in weighted_fields:
        value = str(history.get(field) or "").lower()
        if value and any(term in value for term in terms):
            score += weight
            reasons.append(f"{field} match")

    if score <= 0:
        return 0.0, []

    recency_weight = 0.30 if any(word in query for word in RECENCY_WORDS) else 0.10
    score += _recency_score(history.get("purchased_at"), recency_weight)
    reasons.append("recent purchase")

    satisfaction = history.get("satisfaction_score")
    if isinstance(satisfaction, (int, float)) and satisfaction > 0:
        score += min(float(satisfaction), 5.0) / 5.0 * 0.10
        reasons.append("satisfaction")

    if history.get("product_url"):
        score += 0.05
        reasons.append("product_url exists")

    if history.get("selected_options"):
        score += 0.05
        reasons.append("selected_options exists")

    return score, reasons


def _candidate_from_history(history: dict[str, Any]) -> dict[str, Any]:
    return {
        "purchase_history_id": history.get("id"),
        "product_id": history.get("product_id"),
        "product_option_id": history.get("product_option_id"),
        "product_name": history.get("product_name"),
        "product_url": history.get("product_url"),
        "option_text": history.get("option_text"),
        "selected_options": history.get("selected_options") or {},
        "price_at_purchase": history.get("price_at_purchase", 0),
        "platform": history.get("platform"),
        "purchased_at": history.get("purchased_at"),
        "category": history.get("category"),
        "brand": history.get("brand"),
        "keyword": history.get("keyword"),
    }


def _expand_terms(query: str, keywords: list[str]) -> list[str]:
    raw_terms = [query, *keywords]
    for token in query.replace(",", " ").split():
        raw_terms.append(token)

    terms: list[str] = []
    for raw in raw_terms:
        value = str(raw or "").strip().lower()
        if not value:
            continue
        terms.append(value)
        terms.extend(alias.lower() for alias in KEYWORD_ALIASES.get(value, []))

    seen = set()
    return [term for term in terms if not (term in seen or seen.add(term))]


def _recency_score(value: Any, max_weight: float) -> float:
    purchased_at = _parse_datetime(value)
    if purchased_at == datetime.min.replace(tzinfo=timezone.utc):
        return 0.0

    now = datetime.now(timezone.utc)
    days = max((now - purchased_at).days, 0)
    if days <= 30:
        return max_weight
    if days <= 90:
        return max_weight * 0.7
    if days <= 180:
        return max_weight * 0.4
    return max_weight * 0.2


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
