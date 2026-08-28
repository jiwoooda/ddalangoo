"""HTTP adapter exposing the real Ddalangoo graph to MatrAIx persona-user-sim."""

from __future__ import annotations

import json
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

# ── "이어서 실험"(memory_track) 트랙 영속 저장 ────────────────────────────
# 페르소나 단위로 회차를 이어 돌릴 때(trial_spec.memory_track == true) 구매이력/
# 프로필이 프로세스 재시작 후에도 남도록, mock_db.json 안의 전용 네임스페이스
# "memory_track": {"purchase_history": {persona_*: [...]}, "profiles": {persona_*: {...}}}
# 에 저장한다. 정식 fixture 키(users/addresses/purchase_history/preference_memory)는
# 절대 건드리지 않는다 — 그건 mock_tools._load_external_mock_db()의 기존
# 와이어링이 그대로 담당한다.
_MEMORY_DB_PATH = REPO / "evals" / "data" / "mock_db.json"


def _restore_memory_track() -> None:
    """프로세스 시작 시 mock_db.json의 memory_track 서브키를 인메모리 저장소에
    복원한다. 파일 읽기는 기존 _load_external_mock_db()를 그대로 재사용한다."""
    from src.tools import db_client, mock_tools

    ext = mock_tools._load_external_mock_db() or {}
    track = ext.get("memory_track") or {}
    histories = track.get("purchase_history")
    if isinstance(histories, dict):
        for key, rows in histories.items():
            if key.startswith("persona_"):
                mock_tools.MOCK_PURCHASE_HISTORY[key] = rows
    profiles = track.get("profiles")
    if isinstance(profiles, dict):
        for key, prof in profiles.items():
            if key.startswith("persona_"):
                db_client._mock_profile_store[key] = prof


def _persist_memory_track(user_id: str) -> None:
    """세션 응답 후 이 persona의 구매이력/프로필을 mock_db.json의 memory_track
    네임스페이스에 원자적으로(temp write + rename) 반영한다. persona_* 키가
    아니면(무기억 트랙) 아무것도 하지 않는다. 나머지 최상위 키는 읽은 그대로
    다시 쓴다."""
    if not user_id.startswith("persona_"):
        return
    from src.tools import db_client, mock_tools

    try:
        data = json.loads(_MEMORY_DB_PATH.read_text(encoding="utf-8")) if _MEMORY_DB_PATH.exists() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    track = data.get("memory_track")
    track = dict(track) if isinstance(track, dict) else {}
    histories = dict(track.get("purchase_history") or {})
    profiles = dict(track.get("profiles") or {})

    rows = mock_tools.MOCK_PURCHASE_HISTORY.get(user_id)
    if rows is not None:
        histories[user_id] = rows
    prof = db_client._mock_profile_store.get(user_id)
    if prof is not None:
        profiles[user_id] = prof

    track["purchase_history"] = histories
    track["profiles"] = profiles
    data["memory_track"] = track

    _MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _MEMORY_DB_PATH.with_name(_MEMORY_DB_PATH.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _MEMORY_DB_PATH)


_restore_memory_track()


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


# trial 스펙 탐색 디렉터리. "이어서 실험"(memory_track) 전용 세트를 먼저 보고,
# 없으면 정식 3조건 pilot 세트를 본다. 두 세트는 파일 자체가 다른 디렉터리에
# 있어 섞이지 않는다.
_TRIAL_DATASET_DIRS = (
    "ddalangoo-memory-track",
    "ddalangoo-personalized-shopping-pilot",
)


def _load_shopping_trial(trial_id: str | None) -> dict[str, Any] | None:
    if not trial_id:
        return None
    base = REPO.parents[2] / "MatrAIx-Persona-8B" / "persona" / "datasets"
    for dataset in _TRIAL_DATASET_DIRS:
        path = base / dataset / f"trial_{trial_id}.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


# PersistedSmalltalkProfile(src/state/smalltalk_schema.py)의 리스트형 필드.
# 병합 시 합집합으로 다뤄서 이전 회차에 쌓인 값을 절대 줄이지 않는다.
_PROFILE_LIST_FIELDS = (
    "food_dislikes", "household_notes", "favorite_foods",
    "health_notes", "inconveniences", "allergens", "diet_restrictions",
)


def _merge_preloaded_profile(stored: dict[str, Any], spec_profile: dict[str, Any]) -> dict[str, Any]:
    """이어서 실험(스코프-B) 트랙에서 2회차 이후 _bootstrap이 1회차에 쌓인
    프로필을 지우지 않도록 병합한다.

      - 리스트 필드(allergens/diet_restrictions/health_notes 등): 합집합.
        세션 중 감지돼 저장된 알레르기/식이 정보를 spec의 빈 값이 덮어쓰지
        못하게 한다.
      - additional_signals: (label, value) 기준 중복 제거하며 이어붙임.
      - 스칼라 필드: 기존에 값이 있으면 유지(기존 우선), 없을 때만 spec으로 채움.

    1회차(기존 프로필 없음)에는 이 함수를 타지 않고 spec을 그대로 저장한다.
    """
    from src.tools import db_client
    merged = dict(stored)
    for key, spec_val in spec_profile.items():
        if key == "computed_at":
            continue  # save_profile이 재스탬프한다
        if key in _PROFILE_LIST_FIELDS:
            merged[key] = db_client.merge_list_field(merged.get(key), spec_val or [])
        elif key == "additional_signals":
            seen = {(s.get("label"), s.get("value")) for s in (merged.get(key) or [])}
            extra = [s for s in (spec_val or []) if (s.get("label"), s.get("value")) not in seen]
            merged[key] = (merged.get(key) or []) + extra
        elif not merged.get(key):
            merged[key] = spec_val
    merged.pop("computed_at", None)
    return merged


def _bootstrap_shopping_trial(user_id: str, spec: dict[str, Any]) -> None:
    from src.tools import db_client, mock_tools
    profile = dict(spec.get("preloaded_profile") or {})
    profile.setdefault("onboarded_at", "evaluation_preloaded")
    # 이미 이 페르소나로 쌓인 프로필이 있으면 spec으로 덮어쓰지 않고 병합한다
    # (이어서 실험 트랙 — Unit 2). 기존 프로필이 없으면(1회차) spec을 그대로 저장.
    stored = db_client.get_profile(user_id)
    if stored:
        profile = _merge_preloaded_profile(stored, profile)
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
            # thread_id는 세션마다 고유하게 유지한다 — LangGraph 체크포인트는
            # 대화(=trial) 단위로 분리돼야 한다.
            thread_id = f"matraix_thread_{session_id}"
            config = {"configurable": {"thread_id": thread_id}}
            trial_spec = _load_shopping_trial(request.trialId)
            # user_id: "이어서 실험" 트랙(trial_spec.memory_track == true)에서만
            # persona_id 기반 고정값으로 잡아 회차 간 상태(구매이력/프로필)를 같은
            # 키로 누적한다(스코프-B: baseline/gold/extracted 구분 없음). 정식
            # 3조건 평가 trial은 memory_track 필드가 없으므로 기존처럼 세션별
            # 임시 id로 폴백한다 — 무기억 동작 그대로, 정식 평가 격리 유지.
            memory_track = bool((trial_spec or {}).get("memory_track"))
            persona_id = str((trial_spec or {}).get("persona_id") or "").strip()
            if memory_track and persona_id:
                user_id = f"persona_{persona_id}"
            else:
                user_id = f"matraix_{session_id}"
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
        # 이어서 실험 트랙이면(user_id == persona_*) 이번 응답까지 반영된
        # 구매이력/프로필을 파일에 flush한다. 무기억 트랙은 no-op.
        _persist_memory_track(session["user_id"])
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
