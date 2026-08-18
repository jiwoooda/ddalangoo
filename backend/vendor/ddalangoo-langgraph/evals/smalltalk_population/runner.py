from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .metrics import aggregate_rows, score_conversation, score_profile
from .reporting import write_reports

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORKSPACE = REPO.parents[2]


class PersonaTurn(BaseModel):
    text: str
    disclose: dict[str, Any] = Field(default_factory=dict)


class ExperienceScore(BaseModel):
    trust_competence: int = Field(ge=1, le=5)
    trust_benevolence: int = Field(ge=1, le=5)
    perceived_empathy: int = Field(ge=1, le=5)
    perceived_helpfulness: int = Field(ge=1, le=5)
    ease: int = Field(ge=1, le=5)
    frustration: int = Field(ge=1, le=5)
    goal_status: str
    goal_reasoning: list[str] = Field(default_factory=list)


STATE_KEYS = (
    "stage", "onboarding_started_at", "name_greeting_pending",
    "recent_patterns_used", "recent_episodes_used", "consecutive_question_turns",
    "already_asked_topics", "turns_without_required_progress",
    "health_followup_turns_remaining", "last_asked_topic_field",
    "current_agent", "next_agent", "intent",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _snapshot(values: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(values.get(key)) for key in STATE_KEYS if key in values}


def _extract_reply(values: dict[str, Any]) -> str | None:
    for msg in reversed(values.get("messages", [])):
        role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else None)
        if role in ("ai", "assistant"):
            return getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
    return None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_api_env() -> None:
    for path in (WORKSPACE / ".env", WORKSPACE / "backend" / ".env", REPO / ".env"):
        if path.exists():
            load_dotenv(path, override=False)


def _ensure_graph_compatibility() -> None:
    import langgraph.errors
    from langgraph.runtime import Runtime
    if not hasattr(langgraph.errors, "NodeError"):
        class NodeError(Exception):
            pass
        langgraph.errors.NodeError = NodeError
    # This repository supports a LangGraph revision that exposes retry metadata
    # as Runtime.execution_info. Older installed revisions omit the attribute.
    if not hasattr(Runtime, "execution_info"):
        Runtime.execution_info = None


def _prompt_hash() -> str:
    prompt = REPO / "src" / "prompts" / "smalltalk_prompt.py"
    return hashlib.sha256(prompt.read_bytes()).hexdigest()[:16]


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _llm_judge(persona: dict[str, Any], scenario: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    from langchain_openai import ChatOpenAI
    transcript = "\n".join(f"{e['speaker']}: {e['text']}" for e in events)
    prompt = f"""You evaluate a Korean voice shopping conversation for an older adult.
Persona: {json.dumps(persona, ensure_ascii=False)}
Scenario goal: {json.dumps(scenario, ensure_ascii=False)}
Transcript:\n{transcript}
Score from the persona's perspective. Frustration 1 means none and 5 means severe.
goal_status must be achieved, partially_achieved, failed, or not_applicable.
Use goal_reasoning codes where applicable: intent_misclassification, unnecessary_clarification,
insufficient_clarification, preference_ignored, health_constraint_missed,
topic_recovery_failure, user_abandonment, premature_completion.
"""
    result = ChatOpenAI(model=os.getenv("EVAL_JUDGE_MODEL", "gpt-4o-mini"), temperature=0).with_structured_output(
        ExperienceScore, method="json_schema"
    ).invoke(prompt)
    data = result.model_dump()
    data["trust"] = round((data["trust_competence"] + data["trust_benevolence"]) / 2, 2)
    return data


def run_case(
    persona: dict[str, Any], scenario: dict[str, Any], repeat: int, output_root: Path,
    model: str, judge: bool, temperature: float = 0.0,
) -> dict[str, Any]:
    _ensure_graph_compatibility()
    sys.path.insert(0, str(REPO))
    from src.graph.builder import build_graph
    from src.state.schema import get_default_shopping_state
    from src.tools import db_client

    run_id = f"{persona['id']}-{scenario['id']}-R{repeat:02d}-{uuid.uuid4().hex[:6]}"
    run_dir = output_root / "runs" / run_id
    user_id = f"eval_{run_id}"
    thread_id = f"thread_{run_id}"
    config = {"configurable": {"thread_id": thread_id}}
    os.environ.update({
        "LLM_BACKEND": "api", "CONTEXT_MODEL": model, "DB_MODE": "mock",
        # configs.llm_config.get_llm이 이 값이 세팅돼 있으면 각 에이전트 모듈이
        # 저마다 하드코딩한 temperature를 전부 덮어쓴다 — 실험 재현성을 위해
        # 기본은 0(결정론적)이고, --temperature로 조정 가능.
        "LLM_TEMPERATURE_OVERRIDE": str(temperature),
    })
    db_client.save_profile(user_id, {})

    input_payload = {
        "run_id": run_id, "persona": persona, "scenario": scenario, "repeat": repeat,
        "model": model, "temperature": temperature, "prompt_hash": _prompt_hash(), "started_at": _utc(),
    }
    _json_dump(run_dir / "input.json", input_payload)

    graph = build_graph()
    graph.invoke(get_default_shopping_state(user_id, thread_id), config)
    values = graph.get_state(config).values
    events: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    proactive = _extract_reply(values)
    if proactive:
        events.append({"turn": 0, "timestamp": _utc(), "speaker": "assistant", "text": proactive,
                       "state_after": _snapshot(values)})

    disclosed: dict[str, Any] = {}
    error: dict[str, Any] | None = None
    scripted_turns = persona.get("scripts", {}).get(scenario["id"], scenario.get("turns", []))
    for turn_no, raw_turn in enumerate(scripted_turns, 1):
        turn = PersonaTurn.model_validate(raw_turn)
        before = _snapshot(graph.get_state(config).values)
        disclosed.update(turn.disclose)
        events.append({"turn": turn_no, "timestamp": _utc(), "speaker": "user", "text": turn.text,
                       "semantic_ground_truth": {"disclosed_fields": turn.disclose}})
        try:
            graph.update_state(config, {"messages": [{"role": "user", "content": turn.text}]})
            graph.invoke(None, config)
        except Exception as exc:  # preserve partial run for diagnosis
            error = {"type": type(exc).__name__, "message": str(exc), "turn": turn_no}
            break
        after_values = graph.get_state(config).values
        after = _snapshot(after_values)
        profile = db_client.get_profile(user_id) or {}
        reply = _extract_reply(after_values) or ""
        events.append({"turn": turn_no, "timestamp": _utc(), "speaker": "assistant", "text": reply,
                       "state_after": after})
        state_rows.append({"turn": turn_no, "node": after.get("current_agent"),
                           "state_before": before, "state_after": after,
                           "profile_snapshot": profile})
        if after_values.get("stage") in ("completed", "failed"):
            break

    final_profile = db_client.get_profile(user_id) or {}
    profile_metrics = score_profile(final_profile, disclosed, persona.get("hidden_fields", []))
    conversation_metrics = score_conversation(events)
    experience = _llm_judge(persona, scenario, events) if judge and not error else {
        "trust_competence": None, "trust_benevolence": None, "perceived_empathy": None,
        "perceived_helpfulness": None, "trust": None, "ease": None, "frustration": None,
        "goal_status": "failed" if error else "not_scored", "goal_reasoning": [error["type"]] if error else [],
    }
    metrics = {
        "run_id": run_id, "persona_id": persona["id"], "age": persona["age"],
        "dialect": persona["speech"]["dialect"], "scenario_id": scenario["id"], "repeat": repeat,
        "outcome": {"goal_status": experience["goal_status"], "goal_reasoning": experience["goal_reasoning"]},
        "profile": profile_metrics, "conversation": conversation_metrics, "experience": experience,
        "error": error,
    }
    _jsonl(run_dir / "conversation.jsonl", events)
    _jsonl(run_dir / "state_trace.jsonl", state_rows)
    _json_dump(run_dir / "final_profile.json", final_profile)
    _json_dump(run_dir / "metrics.json", metrics)
    _json_dump(run_dir / "errors.json", [] if error is None else [error])
    return metrics


def _flat(metrics: dict[str, Any]) -> dict[str, Any]:
    p, c, e, o = metrics["profile"], metrics["conversation"], metrics["experience"], metrics["outcome"]
    return {
        "run_id": metrics["run_id"], "persona_id": metrics["persona_id"], "age": metrics["age"],
        "dialect": metrics["dialect"], "scenario_id": metrics["scenario_id"], "repeat": metrics["repeat"],
        "goal_status": o["goal_status"], "goal_reasoning": "|".join(o["goal_reasoning"]),
        "profile_precision": p["precision"], "profile_recall": p["recall"], "profile_f1": p["f1"],
        "hallucination_rate": p["hallucination_rate"], "health_recall": p["health_recall"],
        "total_turns": c["total_turns"], "question_rate": c["question_rate"],
        "question_limit_violation_rate": c["question_limit_violation_rate"],
        "semantic_repeat_rate": c["semantic_repeat_rate"], "trust": e.get("trust"),
        "ease": e.get("ease"), "frustration": e.get("frustration"),
        "error_type": (metrics.get("error") or {}).get("type"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ddalangoo 65+ population smalltalk evaluation")
    parser.add_argument("--personas", default=str(HERE / "personas.json"))
    parser.add_argument("--scenarios", default=str(HERE / "scenarios.json"))
    parser.add_argument("--persona-id", action="append")
    parser.add_argument("--scenario-id", action="append")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument(
        "--temperature", type=float, default=0.0,
        help="모든 에이전트 LLM 호출에 강제 적용할 temperature (재현성을 위해 기본 0)",
    )
    parser.add_argument("--judge", action="store_true", help="Score Trust/Ease/Frustration with a second LLM call")
    parser.add_argument("--output", default=str(REPO / "logs" / "population_evals"))
    parser.add_argument("--experiment-id", default=None, help="Stable output folder name")
    args = parser.parse_args()
    _load_api_env()
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required (workspace .env is supported).")
    personas = _load_json(Path(args.personas))
    scenarios = _load_json(Path(args.scenarios))
    if any(int(p["age"]) < 65 for p in personas):
        raise SystemExit("All evaluation personas must be at least 65 years old.")
    if args.persona_id:
        personas = [p for p in personas if p["id"] in set(args.persona_id)]
    if args.scenario_id:
        scenarios = [s for s in scenarios if s["id"] in set(args.scenario_id)]
    experiment_id = args.experiment_id or datetime.now().strftime("smalltalk_%Y%m%d_%H%M%S")
    root = Path(args.output) / experiment_id
    experiment_config = {
        "experiment_id": experiment_id, "created_at": _utc(), "model": args.model,
        "temperature": args.temperature,
        "judge": args.judge, "repeat": args.repeat, "prompt_hash": _prompt_hash(),
        "git_commit": _git_commit(),
        "persona_ids": [p["id"] for p in personas], "scenario_ids": [s["id"] for s in scenarios],
        "planned_runs": len(personas) * len(scenarios) * args.repeat,
    }
    _json_dump(root / "experiment_config.json", experiment_config)
    rows = []

    def save_progress() -> None:
        with (root / "summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
            if rows:
                writer.writeheader(); writer.writerows(rows)
        _json_dump(root / "report.json", aggregate_rows(rows))
        _json_dump(root / "progress.json", {
            "experiment_id": experiment_id, "completed_runs": len(rows),
            "planned_runs": experiment_config["planned_runs"], "updated_at": _utc(),
            "status": "running" if len(rows) < experiment_config["planned_runs"] else "completed",
        })
        write_reports(root, rows, experiment_config)

    for persona in personas:
        for scenario in scenarios:
            for repeat in range(1, args.repeat + 1):
                print(f"[run] {persona['id']} / {scenario['id']} / {repeat}")
                rows.append(_flat(run_case(
                    persona, scenario, repeat, root, args.model, args.judge, args.temperature
                )))
                save_progress()
    persona_rows = []
    for persona_id in sorted({row["persona_id"] for row in rows}):
        group = [row for row in rows if row["persona_id"] == persona_id]
        report = aggregate_rows(group)
        persona_rows.append({
            "persona_id": persona_id,
            "runs": len(group),
            "profile_f1_mean": report.get("profile_f1", {}).get("mean"),
            "hallucination_rate_mean": report.get("hallucination_rate", {}).get("mean"),
            "question_limit_violation_rate_mean": report.get("question_limit_violation_rate", {}).get("mean"),
            "semantic_repeat_rate_mean": report.get("semantic_repeat_rate", {}).get("mean"),
            "trust_mean": report.get("trust", {}).get("mean"),
            "ease_mean": report.get("ease", {}).get("mean"),
            "frustration_mean": report.get("frustration", {}).get("mean"),
            "goal_completion_rate": report.get("goal_completion_rate"),
        })
    with (root / "persona_summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(persona_rows[0]) if persona_rows else [])
        if persona_rows:
            writer.writeheader(); writer.writerows(persona_rows)
    save_progress()
    print(f"Results: {root}")


if __name__ == "__main__":
    main()
