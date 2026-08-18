"""Living Test 실행기 — unit/integration/e2e 전부 이 하나에서 분기한다.

- unit: 해당 agent의 `*_node(state)` 함수를 그래프 없이 직접 호출한다
  (case의 input+context를 합쳐 state로 넘김) — evals/local_runner.py와 같은
  "그래프 우회, 노드 직접 호출" 정신이되, 거기 클로저를 복제하지 않고
  실제 프로덕션 노드 함수(src/agents/*_node)를 그대로 import해서 쓴다.
- integration/e2e: `src/graph/builder.py::build_graph()`로 실제 그래프를
  invoke하고, `graph.stream(..., stream_mode="updates")`로 어떤 노드가
  실행됐는지(executed_nodes)를 얻는다 — agent_logger의 파일 로깅에
  의존하지 않는, LangGraph 표준 방식.

판정은 assertions.py로 deterministic하게만 한다(LLM Judge 없음). Test
정의(unit/integration/e2e 밑 *.jsonl)는 절대 다시 쓰지 않는다 — 결과는
runs/{scope}/{target}_{timestamp}_{git_sha}.json에만 쓴다.

사용법:
  python -m evals.living_tests.runner --scope unit --target product_agent
  python -m evals.living_tests.runner --scope unit --target product_agent --case product_agent-2026-08-18-001
  python -m evals.living_tests.runner --scope integration --target routing
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_LANGGRAPH_ROOT = Path(__file__).resolve().parents[2]  # backend/vendor/ddalangoo-langgraph
if str(_LANGGRAPH_ROOT) not in sys.path:
    sys.path.insert(0, str(_LANGGRAPH_ROOT))

load_dotenv()
os.environ.setdefault("DB_MODE", "mock")  # local_runner.py와 동일 — 결정론적 로컬 실행

from evals.living_tests import store
from evals.living_tests.assertions import run_assertions, verdict_from_assertions, UnknownAssertionType

BASE_DIR = store.BASE_DIR
RUNS_DIR = BASE_DIR / "runs"

# unit scope target → (모듈 경로, 노드 함수명). local_runner.py의 predict 클로저를
# 복제하지 않고 실제 프로덕션 노드 함수를 그대로 import한다.
_UNIT_NODE = {
    "intent_agent": ("src.agents.intent_agent", "intent_agent_node"),
    "context_agent": ("src.agents.context_agent", "context_agent_node"),
    "product_agent": ("src.agents.product_agent", "product_agent_node"),
    "response_agent": ("src.agents.response_agent", "response_agent_node"),
    "smalltalk_agent": ("src.agents.smalltalk_agent", "smalltalk_agent_node"),
    "reorder_agent": ("src.agents.reorder_agent", "reorder_agent_node"),
    "payment_agent": ("src.payment.node", "payment_agent_node"),
}


def _git_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _ensure_graph_compatibility() -> None:
    """이번 세션 내내 REPL 스크립트에서 써온 LangGraph 버전 호환 shim 그대로
    재사용 — 새로 만든 게 아니라 이미 검증된 패턴."""
    import langgraph.errors
    from langgraph.runtime import Runtime

    if not hasattr(langgraph.errors, "NodeError"):
        class NodeError(Exception):
            pass
        langgraph.errors.NodeError = NodeError
    if not hasattr(Runtime, "execution_info"):
        Runtime.execution_info = None


def _seed_mock_cart(context: dict[str, Any]) -> None:
    """payment_agent처럼 장바구니 상태가 state가 아니라 외부 mock DB(user_id 키,
    src/tools/mock_tools.py의 _mock_carts)에 있는 agent는 state만 채워선 재현이
    안 된다 — context.cart_seed = [{"user_id":..., "product": {...}, "quantity":...,
    "keywords": [...]}, ...]가 있으면 실행 전에 이미 있는 mock_add_to_cart/
    mock_clear_cart를 그대로 불러 미리 담아둔다(새 fixture 시스템 아님, 실제
    프로덕션 mock tool 재사용)."""
    seeds = context.get("cart_seed")
    if not seeds:
        return
    from src.tools.mock_tools import mock_add_to_cart, mock_clear_cart

    default_user_id = context.get("user_id")
    seeded_users: set[str] = set()
    for item in seeds:
        user_id = item.get("user_id", default_user_id)
        if user_id and user_id not in seeded_users:
            mock_clear_cart(user_id)
            seeded_users.add(user_id)
        mock_add_to_cart(user_id, item["product"], item["quantity"], item.get("keywords"))


def _run_unit_case(case: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    """반환: (output, executed_nodes, tool_calls_summary). unit은 노드 하나만
    호출하므로 executed_nodes는 그 노드 이름 하나."""
    target = case["target"]
    if target not in _UNIT_NODE:
        raise store.SchemaError(f"unit scope에 알 수 없는 target: {target!r}")
    module_path, fn_name = _UNIT_NODE[target]
    module = importlib.import_module(module_path)
    node_fn = getattr(module, fn_name)

    context = case.get("context") or {}
    _seed_mock_cart(context)
    state = {**(case.get("input") or {}), **context}
    output = node_fn(state)
    if not isinstance(output, dict):
        output = dict(output or {})
    return output, [target], []


def _run_graph_case(
    case: dict[str, Any], extra_state: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """integration/e2e — 실제 graph.invoke()를 태우고 stream_mode='updates'로
    어떤 노드가 실행됐는지 수집한다.

    extra_state는 Failure 재현(run_reproduction)에서만 쓰인다 — Failure의
    input.state(기계가 읽는 구조화된 초기 state 조각)를 사용자 메시지 주입
    전에 그대로 병합한다. Test 케이스 실행(run_case)에서는 항상 None."""
    _ensure_graph_compatibility()
    from src.graph.builder import build_graph
    from src.state.schema import get_default_shopping_state

    user_input = (case.get("input") or {}).get("user_input") or (case.get("input") or {}).get("user")
    if not user_input:
        raise store.SchemaError(f"integration/e2e 케이스는 input.user_input(또는 input.user)이 필요함: {case['case_id']}")

    context = case.get("context") or {}
    user_id = context.get("user_id", f"living_test_{case['case_id']}")
    _seed_mock_cart(context)

    graph = build_graph()
    session_id = f"living-test-{case['case_id']}"
    config = {"configurable": {"thread_id": session_id}}
    graph.invoke(get_default_shopping_state(user_id, session_id), config)
    if extra_state:
        graph.update_state(config, extra_state)
    graph.update_state(config, {"messages": [{"role": "user", "content": user_input}]})

    executed_nodes: list[str] = []
    for update in graph.stream(None, config, stream_mode="updates"):
        executed_nodes.extend(update.keys())

    output = graph.get_state(config).values
    return output, executed_nodes, []


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    scope = case["scope"]
    executor = _run_unit_case if scope == "unit" else _run_graph_case
    output, executed_nodes, tool_calls_summary = executor(case)

    try:
        assertion_results = run_assertions(case.get("expected_assertions") or [], output, executed_nodes)
    except UnknownAssertionType as e:
        return {
            "case_id": case["case_id"], "trace_ref": None,
            "executed_nodes": executed_nodes, "tool_calls_summary": tool_calls_summary,
            "assertion_results": [], "verdict": "fail", "error": str(e),
        }

    verdict = verdict_from_assertions(assertion_results)
    return {
        "case_id": case["case_id"],
        "trace_ref": None,  # LOG_AGENT_TRACE로 별도 세션을 켜지 않는 한 비어있음 — 필요시 사람이 직접 채움
        "executed_nodes": executed_nodes,
        "tool_calls_summary": tool_calls_summary,
        "assertion_results": assertion_results,
        "verdict": verdict,
    }


def _latest_prior_verdict(case_id: str, before_run_id: str) -> str | None:
    """이 case_id의 가장 최근 이전 run(run_id 기준 시간 정렬)에서의 verdict.
    비교 기준은 항상 '직전 run'으로 고정 — 별도 baseline 개념 없음."""
    candidates: list[tuple[str, str]] = []  # (run_id, verdict)
    for path in RUNS_DIR.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("run_id") == before_run_id:
            continue
        for c in data.get("cases", []):
            if c.get("case_id") == case_id:
                candidates.append((data.get("run_id", ""), c.get("verdict")))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def _regression_summary(run_id: str, case_results: list[dict[str, Any]]) -> list[str]:
    lines = []
    for c in case_results:
        prior = _latest_prior_verdict(c["case_id"], run_id)
        verdict = c["verdict"]
        if prior is None:
            label = f"{verdict}(첫 실행)"
        elif prior == verdict:
            label = f"{verdict}(직전과 동일)"
        elif prior != "pass" and verdict == "pass":
            label = "now_passing"
        elif prior == "pass" and verdict != "pass":
            label = "newly_failing"
        else:
            label = f"{prior}->{verdict}"
        lines.append(f"  [{label}] {c['case_id']}")
    return lines


def run_scope_target(scope: str, target: str, only_case_id: str | None = None) -> Path:
    cases = store.read_cases(scope, target)
    if only_case_id:
        cases = [c for c in cases if c["case_id"] == only_case_id]
        if not cases:
            raise SystemExit(f"케이스를 찾을 수 없습니다: {only_case_id}")

    results = [run_case(c) for c in cases]

    run_id = f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{_git_sha()}"
    run_record = {
        "run_id": run_id, "scope": scope, "target": target,
        "git_sha": _git_sha(), "model": os.getenv("CONTEXT_MODEL", "default"),
        "case_count": len(results), "cases": results,
    }
    out_dir = RUNS_DIR / scope
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{target}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{_git_sha()}.json"
    out_path.write_text(json.dumps(run_record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== {scope}/{target}: {len(results)}개 케이스 실행 ===")
    for r in results:
        print(f"  [{r['verdict']}] {r['case_id']}" + (f"  ({r['error']})" if r.get("error") else ""))
    print("\n=== 직전 run 대비 ===")
    for line in _regression_summary(run_id, results):
        print(line)
    print(f"\n저장됨: {out_path}")
    return out_path


def run_reproduction(failure_id: str) -> Path:
    """REPRODUCE/VALIDATE 단계 — Failure를 지금 커밋에서 다시 실행해서 무엇이
    나오는지만 기록한다(판정 없음). Failure.input.user(+선택적 input.state)만
    쓰고, context_summary는 사람용 설명이라 절대 읽지 않는다. 재현 판정은
    이 결과와 failure['observed_actual']을 비교해서 사람이
    store.set_reproduction()으로 직접 남긴다."""
    failure = store.get_failure(failure_id)
    if failure is None:
        raise SystemExit(f"failure_id를 찾을 수 없습니다: {failure_id}")

    finput = failure.get("input") or {}
    user_input = finput.get("user") or finput.get("user_input")
    if not user_input:
        raise store.SchemaError(f"재현하려면 input.user(또는 input.user_input)가 필요함: {failure_id}")

    case_like = {"case_id": failure_id, "input": {"user_input": user_input}, "context": {}}
    output, executed_nodes, tool_calls_summary = _run_graph_case(case_like, extra_state=finput.get("state"))

    run_id = f"repro-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{_git_sha()}"
    run_record = {
        "run_id": run_id,
        "failure_id": failure_id,
        "git_sha": _git_sha(),
        "model": os.getenv("CONTEXT_MODEL", "default"),
        "trace_ref": None,
        "observed": {"output": output, "executed_nodes": executed_nodes, "tool_calls_summary": tool_calls_summary},
    }
    out_dir = RUNS_DIR / "reproduction"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{failure_id}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{_git_sha()}.json"
    # default=str: graph state의 observed.output에는 LangChain 메시지 객체(AIMessage 등)가
    # 섞여 있어 기본 json 인코더로는 직렬화가 안 됨 — context_routing_eval/smoke_test.py와
    # 같은 패턴으로 처리.
    out_path.write_text(json.dumps(run_record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"\n=== 재현 실행: {failure_id} ===")
    print(f"과거 관찰(observed_actual): {failure.get('observed_actual')}")
    print(f"지금 실행 결과(executed_nodes): {executed_nodes}")
    print(f"\n저장됨: {out_path}")
    print("\n다음: 위 결과를 observed_actual과 비교해서 사람이 재현 여부를 판정하세요:")
    print(f'  python -m evals.living_tests.runner --set-reproduction {failure_id} --status reproduced|not_reproduced|blocked --reason "..."')
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Living Test 실행 — deterministic assertion으로 PASS/FAIL 판정")
    parser.add_argument("--scope", choices=list(store.SCOPES))
    parser.add_argument("--target", help="scope 안의 대상(예: product_agent / routing / workflows)")
    parser.add_argument("--case", dest="case_id", default=None, help="이 케이스 하나만 실행")
    parser.add_argument("--reproduce", dest="reproduce_failure_id", default=None,
                         help="REPRODUCE/VALIDATE: 이 failure_id를 지금 커밋에서 재실행(판정 없음, observed만 기록)")
    parser.add_argument("--set-reproduction", dest="set_repro_failure_id", default=None,
                         help="위 --reproduce 결과를 보고 사람이 재현 여부를 확정할 때 사용하는 failure_id")
    parser.add_argument("--status", choices=list(store.REPRODUCTION_STATUSES), default=None,
                         help="--set-reproduction과 함께: reproduced|not_reproduced|blocked")
    parser.add_argument("--run-ref", default=None, help="--set-reproduction과 함께: 참조할 reproduction run 파일 경로")
    parser.add_argument("--reason", default=None, help="--set-reproduction과 함께: 판정 사유")
    args = parser.parse_args()

    if args.reproduce_failure_id:
        run_reproduction(args.reproduce_failure_id)
        return
    if args.set_repro_failure_id:
        if not args.status:
            raise SystemExit("--set-reproduction에는 --status가 필요합니다")
        store.set_reproduction(args.set_repro_failure_id, args.status, run_ref=args.run_ref, reason=args.reason)
        print(f"기록됨: {args.set_repro_failure_id} reproduction.status = {args.status}")
        return
    if not args.scope or not args.target:
        raise SystemExit("--scope/--target (또는 --reproduce / --set-reproduction)이 필요합니다")
    run_scope_target(args.scope, args.target, only_case_id=args.case_id)


if __name__ == "__main__":
    main()
