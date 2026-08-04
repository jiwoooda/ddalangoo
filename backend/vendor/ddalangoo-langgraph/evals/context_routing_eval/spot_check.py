"""
정성적 스팟체크 — 12건 대표 샘플의 실제 파이프라인 출력을 사람이 읽을 수 있게 덤프.

지표 계산 없음(MRR/NDCG 등 안 함) — "결과가 말이 되는가"를 사람이 직접 읽고
판단하기 위한 원문 그대로의 출력이 목적이다. 909건 전체 실행 전 최종 확인 단계.

사용법:
  python -m evals.context_routing_eval.spot_check
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.context_routing_eval.adapter import (
    ensure_onboarded,
    prepare_candidates_for_eval,
    record_to_intent_input,
    record_to_messages,
    seed_purchase_history,
)

from src.agents.intent_agent import intent_agent_node
from src.agents.context_agent import context_agent_node
from src.agents.product_agent import _filter_results, _rank_with_metadata
from src.agents.response_agent import response_agent_node

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "final_dataset_with_conflicts.jsonl"
OUT_PATH = Path(__file__).resolve().parent / "spot_check_output.md"
SELECT_SEED = 7


def load_records() -> list[dict]:
    records = []
    with open(DATA_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _pick(records, domain, group, has_conflict=False, attribute=None, n=1, seed=SELECT_SEED):
    pool = [
        r for r in records
        if r["meta"]["domain"] == domain
        and r["meta"]["group"] == group
        and r["meta"]["has_conflict"] == has_conflict
    ]
    if attribute:
        pool = [r for r in pool if any(c.get("attribute") == attribute for c in (r.get("conflict_signals") or []))]
    rng = random.Random(seed)
    return rng.sample(pool, min(n, len(pool)))


def select_samples(records: list[dict]) -> list[tuple[str, dict]]:
    """(라벨, record) 튜플 리스트. 라벨은 리포트에서 어떤 케이스 유형인지 보여주는 용도."""
    picks: list[tuple[str, dict]] = []
    for r in _pick(records, "food", "normal", n=2):
        picks.append(("food / normal", r))
    for r in _pick(records, "household", "normal", n=2):
        picks.append(("household / normal", r))
    for r in _pick(records, "food", "A_no_history", n=1):
        picks.append(("food / A_no_history", r))
    for r in _pick(records, "household", "A_no_history", n=1):
        picks.append(("household / A_no_history", r))
    for r in _pick(records, "food", "B_no_signal", n=1):
        picks.append(("food / B_no_signal", r))
    for r in _pick(records, "household", "B_no_signal", n=1):
        picks.append(("household / B_no_signal", r))
    for r in _pick(records, "food", "C_no_smalltalk", n=1):
        picks.append(("food / C_no_smalltalk (유일 1건)", r))
    for r in _pick(records, "food", "normal", has_conflict=True, attribute="brand", n=1):
        picks.append(("CONFLICT / food / attribute=brand", r))
    for r in _pick(records, "household", "normal", has_conflict=True, attribute="dietary_feature", n=2):
        picks.append(("CONFLICT / household / attribute=dietary_feature", r))
    return picks


# ══════════════════════════════════════════════
# 파이프라인 실행 (지표 없이 원문만 수집)
# ══════════════════════════════════════════════

def run_pipeline(record: dict, user_id: str, k: int = 20) -> dict:
    out: dict[str, Any] = {}

    ensure_onboarded(user_id)
    seed_purchase_history(user_id, record)

    # intent
    intent_input = record_to_intent_input(record, user_id)
    intent_out = intent_agent_node(intent_input)
    out["intent"] = intent_out.get("intent")
    out["keywords"] = intent_out.get("keywords") or []
    out["intent_degraded"] = intent_out.get("degraded_mode", False)

    # context (smalltalk -> routed signals)
    context_input = {
        "stage": "idle",
        "intent": "buy",
        "user_id": user_id,
        "keywords": out["keywords"],
        "exclude_keywords": [],
        "messages": record_to_messages(record),
    }
    context_out = context_agent_node(context_input)
    recommendation_context = context_out.get("recommendation_context") or {}
    preference_context = recommendation_context.get("preference_context") or {}
    out["preference_context"] = preference_context

    # candidates -> filter -> rank
    candidates = prepare_candidates_for_eval(record, k=k)
    filtered = _filter_results(candidates, [])
    rank_result = _rank_with_metadata(
        candidates=filtered,
        keywords=out["keywords"],
        condition=None,
        preference_context=preference_context,
    )
    ranked = rank_result.get("ranked_products") or []
    out["ranking_mode"] = rank_result.get("ranking_mode")
    out["ranking_degraded"] = rank_result.get("degraded_mode", False)
    out["top5"] = [
        {"product_name": p.get("product_name"), "final_score": p.get("final_score"), "_asin": p.get("_asin")}
        for p in ranked[:5]
    ]
    gold_asin = record["gold_product"]["asin"]
    gold_rank = next((i + 1 for i, p in enumerate(ranked) if p.get("_asin") == gold_asin), None)
    out["gold_rank"] = gold_rank
    out["gold_title"] = record["gold_product"].get("title")

    # response
    selected = ranked[0] if ranked else None
    response_input = {
        "intent": "buy",
        "keywords": out["keywords"],
        "condition": None,
        "recommendation_context": {"preference_context": preference_context},
        "recommended_products": ranked,
        "current_product_index": 0,
        "selected_product": selected,
        "messages": record_to_messages(record),
        "stage": "searching",
        "quantity": None,
        "user_id": user_id,
    }
    response_out = response_agent_node(response_input)
    out["explanation"] = response_out.get("explanation") or ""
    out["response_degraded"] = response_out.get("degraded_mode", False)

    return out


# ══════════════════════════════════════════════
# 마크다운 렌더링
# ══════════════════════════════════════════════

def render_record(idx: int, label: str, record: dict, result: dict) -> str:
    lines = [f"## {idx}. [{label}] record_id={record['record_id']}", ""]

    has_conflict = record["meta"].get("has_conflict", False)
    if has_conflict:
        lines.append(f"**query_original**: {record['query_original']}")
        lines.append("")
        lines.append(f"**query (병합 후, 실제 시스템 입력)**: {record['query']}")
    else:
        lines.append(f"**query**: {record['query']}")
    lines.append("")

    smalltalk = record.get("smalltalk") or []
    lines.append(f"**smalltalk** ({len(smalltalk)}건): {smalltalk if smalltalk else '(없음)'}")
    lines.append("")

    lines.append(f"**intent_agent 출력**: intent=`{result['intent']}`  degraded={result['intent_degraded']}")
    lines.append(f"  keywords: {result['keywords']}")
    lines.append("")

    pref = result["preference_context"]
    lines.append("**context_agent 분류 결과**:")
    lines.append(f"  - soft_preferences: {pref.get('soft_preferences', [])}")
    lines.append(f"  - exclude_additions: {pref.get('exclude_additions', [])}")
    lines.append(f"  - overridden_exclusions: {pref.get('overridden_exclusions', [])}")
    lines.append(f"  - safety_constraints: {pref.get('safety_constraints', [])}")
    lines.append("")

    lines.append(f"**랭킹** (mode={result['ranking_mode']}, degraded={result['ranking_degraded']}):")
    for rank, p in enumerate(result["top5"], start=1):
        marker = "  <- GOLD" if p.get("_asin") and result["gold_rank"] == rank else ""
        lines.append(f"  {rank}. {p['product_name']}  (score={p['final_score']}){marker}")
    lines.append(f"  gold_product: {result['gold_title']!r}  실제 순위: {result['gold_rank'] or '20위 밖(미포함)'}")
    lines.append("")

    lines.append(f"**response_agent 응답 문장** (degraded={result['response_degraded']}):")
    lines.append(f"> {result['explanation']}")
    lines.append("")

    if has_conflict:
        lines.append("### ⚖️ Conflict 신호 vs 실제 반영 여부")
        for cs in record.get("conflict_signals") or []:
            lines.append(
                f"  - attribute=`{cs.get('attribute')}`  direction_or_value=`{cs.get('direction_or_value')}`  "
                f"expected_priority_winner=`{cs.get('expected_priority_winner')}`"
            )
        lines.append("")
        lines.append(
            "  위 overridden_exclusions/exclude_additions 목록과 랭킹 결과를 보고, "
            "expected_priority_winner가 실제로 반영됐는지(예: current_intent가 이겨야 하면 "
            "해당 속성이 overridden_exclusions에 있고 최종 후보에서 배제되지 않았는지) 사람이 판단."
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"[spot_check] 데이터 로드: {DATA_PATH}")
    records = load_records()
    samples = select_samples(records)
    print(f"[spot_check] 선정된 샘플 {len(samples)}건:")
    for label, r in samples:
        print(f"  - [{label}] {r['record_id']}")

    md_parts = [
        "# 정성적 스팟체크 결과",
        "",
        f"데이터: `{DATA_PATH.name}`  샘플 {len(samples)}건  모델: GPT-4o-mini (temperature=0 각 에이전트 설정 기준)",
        "",
        "지표 계산 없음 — 사람이 직접 읽고 '말이 되는지' 판단하는 용도.",
        "",
        "---",
        "",
    ]

    for idx, (label, record) in enumerate(samples, start=1):
        user_id = record.get("meta", {}).get("user_id", record["record_id"])
        print(f"\n[{idx}/{len(samples)}] {label} — {record['record_id']} 실행 중...")
        try:
            result = run_pipeline(record, user_id)
        except Exception as e:
            print(f"  !! 예외 발생: {e}")
            md_parts.append(f"## {idx}. [{label}] record_id={record['record_id']} — 예외 발생\n\n```\n{e}\n```\n\n---\n")
            continue
        section = render_record(idx, label, record, result)
        print(section)
        md_parts.append(section)

    OUT_PATH.write_text("\n".join(md_parts), encoding="utf-8")
    print(f"\n[spot_check] 마크다운 저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
