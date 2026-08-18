"""HTTP adapter exposing the real Ddalangoo graph to MatrAIx persona-user-sim."""

from __future__ import annotations

import os
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

app = FastAPI(title="Ddalangoo MatrAIx Smalltalk Bridge")
_sessions: dict[str, dict[str, Any]] = {}
_lock = Lock()
_graph: Any = None

STATE_KEYS = (
    "stage", "name_greeting_pending", "recent_patterns_used",
    "recent_episodes_used", "consecutive_question_turns", "already_asked_topics",
    "turns_without_required_progress", "health_followup_turns_remaining",
    "last_asked_topic_field", "current_agent", "next_agent", "intent",
    "degraded_mode", "failure_stage", "degradation_reason",
)


class MessageRequest(BaseModel):
    sessionId: str | None = None
    message: str
    title: str | None = None
    applicationId: str | None = None
    applicationContext: str | None = None
    engine: str | None = None
    botType: str | None = None
    trialId: str | None = None


def _ensure_compatibility() -> None:
    import langgraph.errors
    from langgraph.runtime import Runtime
    if not hasattr(langgraph.errors, "NodeError"):
        langgraph.errors.NodeError = type("NodeError", (Exception,), {})
    if not hasattr(Runtime, "execution_info"):
        Runtime.execution_info = None


def _get_graph() -> Any:
    global _graph
    if _graph is None:
        workspace = REPO.parents[2]
        for env_path in (workspace / ".env", workspace / "backend" / ".env"):
            if env_path.is_file():
                load_dotenv(env_path, override=False)
        # Population evaluation needs a frozen candidate set so profile
        # conditions see identical products and hidden product IDs remain
        # objectively scorable. This affects only the dedicated eval bridge;
        # production keeps backend/.env SEARCH_MODE=mcp and the Coupang API.
        os.environ["SEARCH_MODE"] = os.getenv("DDALANGOO_EVAL_SEARCH_MODE", "mock")
        _ensure_compatibility()
        from src.graph.builder import build_graph
        _graph = build_graph()
    return _graph


def _reply(values: dict[str, Any]) -> str:
    for message in reversed(values.get("messages", [])):
        role = getattr(message, "type", None) or (message.get("role") if isinstance(message, dict) else None)
        if role in {"ai", "assistant"}:
            content = getattr(message, "content", None)
            if content is None and isinstance(message, dict):
                content = message.get("content")
            return str(content or "")
    return ""


def _state(values: dict[str, Any]) -> dict[str, Any]:
    keys = STATE_KEYS + ("ranking_mode", "source_used", "keywords", "exclude_keywords", "negative_constraints", "condition", "scored_products", "recommended_products", "selected_product", "quantity", "cart_items", "order_id", "pending_action", "last_agent")
    return {key: deepcopy(values.get(key)) for key in keys if key in values}


def _load_shopping_trial(trial_id: str | None) -> dict[str, Any] | None:
    if not trial_id:
        return None
    path = REPO.parents[2] / "MatrAIx-Persona-8B" / "persona" / "datasets" / "ddalangoo-personalized-shopping-pilot" / f"trial_{trial_id}.json"
    if not path.is_file():
        return None
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def _bootstrap_shopping_trial(user_id: str, spec: dict[str, Any]) -> None:
    from src.tools import db_client, mock_tools
    profile = dict(spec.get("preloaded_profile") or {})
    profile.setdefault("onboarded_at", "evaluation_preloaded")
    db_client.save_profile(user_id, profile)
    category = str((spec.get("purchase_goal") or {}).get("target_category") or "")
    if category and spec.get("candidate_products"):
        mock_tools.MOCK_PRODUCTS[category] = deepcopy(spec["candidate_products"])
    mock_tools.MOCK_ADDRESSES[user_id] = {
        "id": f"eval_addr_{user_id}", "address_label": "집", "recipient_name": "평가 사용자",
        "recipient_phone": "010-0000-0000", "address_line1": "서울특별시 중구 평가로 1",
        "address_line2": "", "zip_code": "00000", "delivery_request": "문 앞", "is_default": True,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/messages")
def send_message(request: MessageRequest) -> dict[str, Any]:
    text = request.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message must not be empty")
    os.environ.setdefault("DB_MODE", "mock")
    graph = _get_graph()
    with _lock:
        session_id = request.sessionId or uuid.uuid4().hex
        session = _sessions.get(session_id)
        if session is None:
            from src.state.schema import get_default_shopping_state
            from src.tools import db_client
            user_id = f"matraix_{session_id}"
            thread_id = f"matraix_thread_{session_id}"
            config = {"configurable": {"thread_id": thread_id}}
            trial_spec = _load_shopping_trial(request.trialId)
            if trial_spec:
                _bootstrap_shopping_trial(user_id, trial_spec)
            else:
                db_client.save_profile(user_id, {})
            graph.invoke(get_default_shopping_state(user_id, thread_id), config)
            session = {"user_id": user_id, "config": config, "turns": [], "trial_id": request.trialId, "trial_spec": trial_spec, "cart_events": [], "seen_cart_ids": set(), "recommendation_events": []}
            _sessions[session_id] = session
        try:
            graph.update_state(session["config"], {"messages": [{"role": "user", "content": text}]})
            graph.invoke(None, session["config"])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
        from src.tools import db_client
        values = graph.get_state(session["config"]).values
        reply = _reply(values)
        profile = db_client.get_profile(session["user_id"]) or {}
        cart = values.get("cart_items") or []
        current_ids: set[str] = set()
        for item in cart:
            raw_product = item.get("product") or item
            item_id = str(raw_product.get("product_id") or item.get("product_url") or item.get("product_name"))
            current_ids.add(item_id)
            if item_id not in session["seen_cart_ids"]:
                session["cart_events"].append({"action": "add", "product_id": item_id, "violated_constraints": deepcopy(raw_product.get("violated_constraints") or []), "turn": len(session["turns"]) + 1})
        session["seen_cart_ids"].update(current_ids)
        spec = session.get("trial_spec") or {}
        ranked = values.get("recommended_products") or []
        goal = spec.get("purchase_goal") or {}
        risky = []
        for rank, product in enumerate(ranked, 1):
            violations = set(product.get("violated_constraints") or [])
            if violations & set(goal.get("forbidden_attributes") or []): risky.append(rank)
        selected = values.get("selected_product") or {}
        prior_turn = session["turns"][-1] if session["turns"] else None
        prior_candidates = (prior_turn.get("evaluation") or {}).get("ranking_trace", {}).get("candidates", []) if prior_turn else []
        if prior_turn and any(candidate.get("rank") is not None for candidate in prior_candidates):
            normalized = text.replace(" ", "")
            if any(token in normalized for token in ("다른", "별로", "싫", "안살", "안사", "비싸", "말고")):
                behavior = "reject"
            elif any(token in normalized for token in ("얼마", "가격", "배송", "성분", "용량", "어떤", "확인", "다시", "비교")) or "?" in text:
                behavior = "clarify_or_research"
            elif any(token in normalized for token in ("그걸로", "살게", "사줘", "담아", "좋아", "괜찮")):
                behavior = "accept"
            else:
                behavior = "other"
            session["recommendation_events"].append({"behavior": behavior, "utterance": text, "after_turn": len(session["turns"]), "selected_product_id_after_response": selected.get("product_id") or selected.get("product_url")})
        ranked_ids = {p.get("product_id") or p.get("product_url") for p in ranked}
        catalog_trace = []
        for product in spec.get("candidate_products") or []:
            pid = product.get("product_id") or product.get("product_url")
            rank = next((i for i,p in enumerate(ranked,1) if (p.get("product_id") or p.get("product_url")) == pid), None)
            catalog_trace.append({"product_id": pid, "rank": rank, "filtered_out": bool(ranked) and pid not in ranked_ids, "violated_constraints": deepcopy(product.get("violated_constraints") or [])})
        eval_state = {"trial_id": session.get("trial_id"), "purchase_goal": deepcopy(goal), "acceptance_criteria": deepcopy(spec.get("acceptance_criteria") or {}), "profile_condition": spec.get("profile_condition"), "initial_profile": deepcopy(spec.get("preloaded_profile") or {}), "session_constraints": {"keywords": deepcopy(values.get("keywords") or []), "exclude_keywords": deepcopy(values.get("exclude_keywords") or []), "negative_constraints": deepcopy(values.get("negative_constraints") or []), "condition": values.get("condition")}, "smalltalk_agent_called": any(t.get("state", {}).get("last_agent") == "smalltalk_agent" for t in session["turns"]) or values.get("last_agent") == "smalltalk_agent", "ranking_trace": {"candidates": catalog_trace, "risky_product_rank": risky[0] if risky else None, "risky_products_filtered": [p["product_id"] for p in catalog_trace if p["filtered_out"] and set(p["violated_constraints"]) & set(goal.get("forbidden_attributes") or [])]}, "recommendation_events": deepcopy(session["recommendation_events"]), "selected_product_id": selected.get("product_id") or selected.get("product_url"), "selected_product_violated_constraints": deepcopy(selected.get("violated_constraints") or []), "selected_quantity": values.get("quantity"), "cart_events": deepcopy(session["cart_events"]), "mock_payment_completed": values.get("stage") == "completed"}
        turn = {
            "userMessage": text,
            "assistantMessage": reply,
            "state": _state(values),
            "profile": profile,
            "evaluation": eval_state,
        }
        session["turns"].append(turn)
        return {
            "sessionId": session_id,
            "reply": reply,
            "turn": turn,
            "structuredExposure": {"state": turn["state"], "profile": profile, "evaluation": eval_state},
        }


@app.get("/v1/sessions/{session_id}")
def session_detail(session_id: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session")
    return {"sessionId": session_id, "turns": session["turns"]}


@app.get("/v1/conversation")
def conversation(sessionId: str) -> dict[str, Any]:
    session = _sessions.get(sessionId)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session")
    messages = []
    for turn in session["turns"]:
        messages.append({"role": "user", "content": turn["userMessage"]})
        messages.append({
            "role": "assistant", "content": turn["assistantMessage"],
            "state": turn["state"], "profile": turn["profile"], "evaluation": turn.get("evaluation"),
        })
    return {"sessionId": sessionId, "messages": messages, "turns": session["turns"]}
