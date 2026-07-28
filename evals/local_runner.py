"""
로컬 evaluator 러너 — LangSmith 없이 evals/data/*.json + evaluators.py로
직접 실행한다. LangSmith 트레이스/데이터셋을 전혀 거치지 않으므로 할당량과
무관하게 항상 돌릴 수 있다.

predict 로직은 run_experiment.py의 run_X_experiment 안에 클로저로만
존재해서 그대로 import할 수 없다 — 여기서는 그 로직을 그대로 복제했다
(run_experiment.py는 LangSmith 경로 전용으로 그대로 둔다, 건드리지 않음).

결과는 evals/runs/{agent}_{시각}_{git commit}.json 에 저장되고,
dashboard.py가 이 파일들을 읽어서 버전 간 지표 비교 + 그 시점 프롬프트
diff를 보여준다.

사용법: python -m evals.local_runner --agent context
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("DB_MODE", "mock")  # 결정론적 로컬 실행 — 실 DB 안 씀

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(exist_ok=True)


def _git_short_hash() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _load_cases(dataset_file: str) -> list[dict[str, Any]]:
    path = DATA_DIR / dataset_file
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("cases", [])


def _case_label(case: dict[str, Any], index: int) -> str:
    inputs = case.get("input", {})
    return (
        inputs.get("scenario")
        or case.get("_comment")
        or inputs.get("user_input")
        or f"case_{index}"
    )


def _score_cases(
    cases: list[dict[str, Any]],
    predict: Callable[[dict[str, Any]], dict[str, Any]],
    evaluators: list[Callable[[dict, dict], dict]],
    reference_key: str = "output",
) -> list[dict[str, Any]]:
    results = []
    for i, case in enumerate(cases):
        inputs = case.get("input", {})
        reference = case.get(reference_key) or case.get("expected_output") or {}
        try:
            outputs = predict(inputs)
        except Exception as e:
            outputs = {"_error": str(e)}

        scores = {}
        for evaluator in evaluators:
            try:
                result = evaluator(outputs, reference)
                scores[result["key"]] = result
            except Exception as e:
                name = getattr(evaluator, "__name__", "unknown_evaluator")
                scores[name] = {"key": name, "score": None, "comment": f"평가 오류: {e}"}

        results.append({
            "case_id": _case_label(case, i),
            "input": inputs,
            "outputs": {k: v for k, v in outputs.items() if not k.startswith("_")},
            "scores": scores,
        })
    return results


def _aggregate(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = sorted({k for c in case_results for k in c["scores"]})
    aggregate = {}
    for name in metric_names:
        values = [
            c["scores"][name]["score"] for c in case_results
            if isinstance(c["scores"].get(name, {}).get("score"), (int, float))
        ]
        aggregate[name] = {
            "mean": round(sum(values) / len(values), 4) if values else None,
            "n": len(values),
        }
    return aggregate


def _save_run(agent: str, backend: str, model: str | None, case_results: list[dict[str, Any]]) -> Path:
    commit = _git_short_hash()
    run_record = {
        "agent": agent,
        "timestamp": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "backend": backend,
        "model": model or "default",
        "case_count": len(case_results),
        "aggregate": _aggregate(case_results),
        "cases": case_results,
    }
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_path = RUNS_DIR / f"{agent}_{ts}_{commit}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(run_record, f, ensure_ascii=False, indent=2)
    return out_path


# ── context_agent ──────────────────────────────────────────────────────────

def run_context_local(backend: str = "api", model: str | None = None) -> Path:
    from evals.run_experiment import _set_backend, _init_usage, _attach_metrics
    from evals.evaluators import CONTEXT_EVALUATORS
    from src.agents.context_agent import build_preference_context, _fetch_purchase_histories

    _set_backend(backend, model, "context")
    cases = _load_cases("context_agent.json")

    def predict(inputs: dict[str, Any]) -> dict[str, Any]:
        user_id = inputs.get("user_id", "")
        keywords = inputs.get("keywords", [])
        _init_usage()
        started = time.perf_counter()
        histories = _fetch_purchase_histories(user_id)
        pref = build_preference_context(user_id, keywords)
        retrieval_context = [
            f"{h.get('product_name', '')} / 브랜드:{h.get('brand', '')} / "
            f"가격:{h.get('price_at_purchase', '')}원 / 플랫폼:{h.get('platform', '')}"
            for h in histories
        ] or ["구매이력 없음"]
        result = {
            **pref,
            "summary": pref.get("keyword_summary") or pref.get("summary", ""),
            "preference_context": pref,
            "purchase_count": len(histories),
            "keyword_history_count": len(pref.get("keyword_history") or []),
            "_retrieval_context": retrieval_context,
        }
        return _attach_metrics(result, (time.perf_counter() - started) * 1000, "context", backend)

    case_results = _score_cases(cases, predict, CONTEXT_EVALUATORS)
    return _save_run("context", backend, model, case_results)


# ── intent_agent ────────────────────────────────────────────────────────────

def run_intent_local(backend: str = "api", model: str | None = None) -> Path:
    from evals.run_experiment import _set_backend, _init_usage, _attach_metrics
    from evals.evaluators import INTENT_EVALUATORS
    from src.state.schema import get_default_shopping_state
    from src.agents.intent_agent import intent_agent_node

    _set_backend(backend, model, "intent")
    cases = _load_cases("intent_agent.json")

    def predict(inputs: dict[str, Any]) -> dict[str, Any]:
        _init_usage()
        started = time.perf_counter()
        # 신규유저 온보딩 게이트(route_entry, src/graph/router.py)는 그래프
        # 레벨 조건부 엣지라 intent_agent_node를 여기처럼 직접 호출하면 애초에
        # 안 걸린다. 그래도 이 데이터셋은 순수 분류 정확도 테스트이므로,
        # 실제 서비스에서도 온보딩을 거쳤을 법한 구매이력 있는 user_001을 쓴다.
        state = get_default_shopping_state("user_001", "eval-session")
        state["messages"] = [{"role": "user", "content": inputs["user_input"]}]
        state["stage"] = inputs.get("stage", "idle")
        if pending := inputs.get("pending_action"):
            state["pending_action"] = {"type": pending}
        try:
            result = intent_agent_node(state)
            result["_schema_ok"] = True
        except Exception as e:
            result = {"intent": "unclear", "keywords": [], "_schema_ok": False, "_error": str(e)}
        return _attach_metrics(result, (time.perf_counter() - started) * 1000, "intent", backend)

    case_results = _score_cases(cases, predict, INTENT_EVALUATORS)
    return _save_run("intent", backend, model, case_results)


# ── product_agent ───────────────────────────────────────────────────────────

def run_product_local(backend: str = "api", model: str | None = None) -> Path:
    from evals.run_experiment import _set_backend, _init_usage, _attach_metrics
    from evals.evaluators import PRODUCT_EVALUATORS
    from src.agents.product_agent import _filter_results, _rank_with_metadata

    _set_backend(backend, model, "product")
    cases = _load_cases("product_agent.json")

    def predict(inputs: dict[str, Any]) -> dict[str, Any]:
        _init_usage()
        started = time.perf_counter()
        try:
            candidates = _filter_results(inputs["candidates"], inputs.get("exclude_keywords", []))
            ranked_result = _rank_with_metadata(
                candidates=candidates,
                keywords=inputs.get("keywords", []),
                condition=inputs.get("condition"),
                preference_context=inputs.get("preference_context", {}),
            )
            ranked = ranked_result["ranked_products"]
            result = {
                "ranked_products": ranked,
                "top_product": ranked[0] if ranked else None,
                "tool_call_success": ranked_result.get("tool_call_success", False),
                "tool_call_error": ranked_result.get("tool_call_error"),
            }
        except Exception as e:
            result = {
                "ranked_products": [],
                "top_product": None,
                "tool_call_success": False,
                "tool_call_error": str(e),
                "_error": str(e),
            }
        return _attach_metrics(result, (time.perf_counter() - started) * 1000, "product", backend)

    case_results = _score_cases(cases, predict, PRODUCT_EVALUATORS)
    return _save_run("product", backend, model, case_results)


# ── response_agent ──────────────────────────────────────────────────────────

def run_response_local(backend: str = "api", model: str | None = None) -> Path:
    from evals.run_experiment import _set_backend, _init_usage, _attach_metrics
    from evals.evaluators import RESPONSE_EVALUATORS
    from src.state.schema import get_default_shopping_state
    from src.agents.response_agent import response_agent_node

    _set_backend(backend, model, "response")
    cases = _load_cases("response_agent.json")

    def predict(inputs: dict[str, Any]) -> dict[str, Any]:
        _init_usage()
        started = time.perf_counter()
        state = get_default_shopping_state("user_eval", "eval-session")
        state["intent"] = "ask" if inputs.get("task") == "qa" else "buy"
        state["selected_product"] = inputs["product"]
        state["keywords"] = inputs.get("keywords", [])
        state["condition"] = inputs.get("condition")
        state["messages"] = [{"role": "user", "content": inputs.get("question") or "이 상품 설명해줘"}]
        state["recommendation_context"] = {"preference_context": inputs.get("preference_context", {})}
        try:
            result = response_agent_node(state)
        except Exception as e:
            result = {"explanation": "", "_error": str(e)}
        return _attach_metrics(result, (time.perf_counter() - started) * 1000, "response", backend)

    case_results = _score_cases(cases, predict, RESPONSE_EVALUATORS)
    return _save_run("response", backend, model, case_results)


AGENT_RUNNERS: dict[str, Callable[..., Path]] = {
    "context": run_context_local,
    "intent": run_intent_local,
    "product": run_product_local,
    "response": run_response_local,
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="로컬 evaluator 러너 (LangSmith 불필요)")
    parser.add_argument("--agent", choices=list(AGENT_RUNNERS), default="context")
    parser.add_argument("--backend", choices=["api", "ollama"], default="api")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    out_path = AGENT_RUNNERS[args.agent](args.backend, args.model)
    with open(out_path, encoding="utf-8") as f:
        record = json.load(f)

    print(f"\n저장됨: {out_path}")
    print(f"agent={record['agent']}  git={record['git_commit']}  cases={record['case_count']}")
    print(f"{'─'*50}")
    for name, agg in sorted(record["aggregate"].items()):
        print(f"  {name:<30} mean={agg['mean']}  n={agg['n']}")


if __name__ == "__main__":
    main()
