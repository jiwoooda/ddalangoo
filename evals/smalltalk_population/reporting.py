from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .metrics import aggregate_rows


TARGETS = {
    "profile_f1": (">=", 0.90),
    "hallucination_rate": ("<=", 0.02),
    "question_limit_violation_rate": ("<=", 0.02),
    "semantic_repeat_rate": ("<=", 0.05),
    "trust": (">=", 4.0),
    "ease": (">=", 4.0),
    "frustration": ("<=", 2.0),
    "goal_completion_rate": (">=", 0.90),
}


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) not in (None, "")]
    return round(sum(values) / len(values), 4) if values else None


def _goal_rate(rows: list[dict[str, Any]]) -> float | None:
    scored = [row for row in rows if row.get("goal_status") not in (None, "", "not_scored")]
    return round(sum(row["goal_status"] == "achieved" for row in scored) / len(scored), 4) if scored else None


def group_summary(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "unknown")].append(row)
    output = []
    for name, group in sorted(groups.items()):
        output.append({
            key: name, "runs": len(group), "profile_f1": _mean(group, "profile_f1"),
            "hallucination_rate": _mean(group, "hallucination_rate"),
            "health_recall": _mean(group, "health_recall"),
            "question_limit_violation_rate": _mean(group, "question_limit_violation_rate"),
            "semantic_repeat_rate": _mean(group, "semantic_repeat_rate"),
            "trust": _mean(group, "trust"), "ease": _mean(group, "ease"),
            "frustration": _mean(group, "frustration"), "goal_completion_rate": _goal_rate(group),
        })
    return output


def _status(value: float | None, operator: str, target: float) -> str:
    if value is None:
        return "N/A"
    passed = value >= target if operator == ">=" else value <= target
    return "PASS" if passed else "FAIL"


def build_detailed_report(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    overall = aggregate_rows(rows)
    outcomes = Counter(str(row.get("goal_status") or "unknown") for row in rows)
    reasons = Counter()
    errors = Counter()
    for row in rows:
        reasons.update(filter(None, str(row.get("goal_reasoning") or "").split("|")))
        if row.get("error_type"):
            errors[str(row["error_type"])] += 1
    headline = {
        "profile_f1": overall.get("profile_f1", {}).get("mean"),
        "hallucination_rate": overall.get("hallucination_rate", {}).get("mean"),
        "question_limit_violation_rate": overall.get("question_limit_violation_rate", {}).get("mean"),
        "semantic_repeat_rate": overall.get("semantic_repeat_rate", {}).get("mean"),
        "trust": overall.get("trust", {}).get("mean"),
        "ease": overall.get("ease", {}).get("mean"),
        "frustration": overall.get("frustration", {}).get("mean"),
        "goal_completion_rate": overall.get("goal_completion_rate"),
    }
    thresholds = {
        key: {"value": headline[key], "operator": op, "target": target,
              "status": _status(headline[key], op, target)}
        for key, (op, target) in TARGETS.items()
    }
    worst = sorted(
        rows,
        key=lambda row: (
            row.get("goal_status") == "achieved",
            float(row.get("profile_f1") or 0),
            -float(row.get("frustration") or 0),
        ),
    )[:10]
    return {
        "experiment": config, "overall": overall, "headline_metrics": headline,
        "acceptance_thresholds": thresholds,
        "by_persona": group_summary(rows, "persona_id"),
        "by_scenario": group_summary(rows, "scenario_id"),
        "by_dialect": group_summary(rows, "dialect"),
        "outcome_distribution": dict(outcomes), "failure_reason_distribution": dict(reasons),
        "error_distribution": dict(errors), "worst_runs": worst,
    }


def _fmt(value: Any) -> str:
    return "N/A" if value is None else str(value)


def _table(items: list[dict[str, Any]], group_key: str) -> list[str]:
    lines = [
        f"| {group_key} | runs | Profile F1 | Hallucination | Health Recall | Trust | Ease | Frustration | Goal rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in items:
        lines.append("| " + " | ".join(_fmt(item.get(k)) for k in (
            group_key, "runs", "profile_f1", "hallucination_rate", "health_recall",
            "trust", "ease", "frustration", "goal_completion_rate",
        )) + " |")
    return lines


def write_reports(root: Path, rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    report = build_detailed_report(rows, config)
    (root / "detailed_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 딸랑구 65+ Smalltalk 정량평가 보고서", "",
        f"- Experiment: `{config.get('experiment_id')}`",
        f"- Model: `{config.get('model')}` / Judge: `{config.get('judge')}`",
        f"- Planned runs: {config.get('planned_runs')} / Completed runs: {len(rows)}",
        f"- Prompt hash: `{config.get('prompt_hash')}` / Git: `{config.get('git_commit')}`", "",
        "## 1. 핵심 지표 및 합격 기준", "",
        "| Metric | Result | Target | Status |", "|---|---:|---:|---|",
    ]
    for key, item in report["acceptance_thresholds"].items():
        lines.append(f"| {key} | {_fmt(item['value'])} | {item['operator']} {item['target']} | {item['status']} |")
    lines += ["", "## 2. 시나리오별 결과", ""] + _table(report["by_scenario"], "scenario_id")
    lines += ["", "## 3. 페르소나별 결과", ""] + _table(report["by_persona"], "persona_id")
    lines += ["", "## 4. 말투별 결과", ""] + _table(report["by_dialect"], "dialect")
    lines += ["", "## 5. 실패 분석", "",
              f"- Goal outcomes: `{json.dumps(report['outcome_distribution'], ensure_ascii=False)}`",
              f"- Goal reasons: `{json.dumps(report['failure_reason_distribution'], ensure_ascii=False)}`",
              f"- Runtime errors: `{json.dumps(report['error_distribution'], ensure_ascii=False)}`", "",
              "## 6. 취약 실행 10건", "",
              "| run_id | persona | scenario | goal | Profile F1 | Trust | Ease | Frustration | reason |",
              "|---|---|---|---|---:|---:|---:|---:|---|" ]
    for row in report["worst_runs"]:
        lines.append("| " + " | ".join(_fmt(row.get(k)) for k in (
            "run_id", "persona_id", "scenario_id", "goal_status", "profile_f1",
            "trust", "ease", "frustration", "goal_reasoning",
        )) + " |")
    lines += ["", "## 7. 해석 원칙", "",
              "- Profile Recall은 실제 발화로 공개된 필드만 분모로 사용한다.",
              "- Trust/Ease/Frustration은 LLM Judge 자동평가이며 코드 기반 지표와 분리해 해석한다.",
              "- 평균뿐 아니라 사투리·건강 제약·과묵형의 최저 성능과 원문 로그를 함께 검토한다.",
              "- API 키와 개인정보는 보고서에 저장하지 않는다.", ""]
    (root / "detailed_report.md").write_text("\n".join(lines), encoding="utf-8")
    return report

