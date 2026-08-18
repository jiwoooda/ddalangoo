from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable


EMPTY = (None, "", [])
LIST_FIELDS = {
    "food_dislikes", "household_notes", "favorite_foods", "health_notes",
    "inconveniences", "allergens", "diet_restrictions",
}


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", "", value).lower()
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def value_matches(expected: Any, actual: Any) -> bool:
    """Lenient comparison for Korean free-text list fields, strict for enums."""
    if isinstance(expected, list):
        actual_values = actual if isinstance(actual, list) else []
        normalized_actual = [_norm(v) for v in actual_values]
        return all(
            any(e == a or (isinstance(e, str) and isinstance(a, str) and (e in a or a in e))
                for a in normalized_actual)
            for e in [_norm(v) for v in expected]
        )
    return _norm(expected) == _norm(actual)


def score_profile(
    final_profile: dict[str, Any],
    disclosed: dict[str, Any],
    hidden_fields: Iterable[str] = (),
) -> dict[str, Any]:
    """Compare only facts the simulated user disclosed during this run."""
    hidden = set(hidden_fields)
    correct: list[str] = []
    wrong: list[str] = []
    missed: list[str] = []
    hallucinated: list[str] = []

    for field, expected in disclosed.items():
        actual = final_profile.get(field)
        if actual in EMPTY:
            missed.append(field)
        elif value_matches(expected, actual):
            correct.append(field)
        else:
            wrong.append(field)

    ignored = {"onboarded_at", "computed_at", "preferred_name"}
    for field, actual in final_profile.items():
        if field in ignored or actual in EMPTY or field in disclosed:
            continue
        # Hidden facts are deliberately unknown to the SUT; saving them is hallucination.
        if field in hidden or field not in disclosed:
            hallucinated.append(field)

    predicted = len(correct) + len(wrong) + len(hallucinated)
    relevant = len(disclosed)
    precision = len(correct) / predicted if predicted else (1.0 if not relevant else 0.0)
    recall = len(correct) / relevant if relevant else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    health_fields = {"health_notes", "allergens", "diet_restrictions"} & set(disclosed)
    health_correct = health_fields & set(correct)
    health_recall = len(health_correct) / len(health_fields) if health_fields else None
    return {
        "correct_fields": correct,
        "wrong_fields": wrong,
        "missed_fields": missed,
        "hallucinated_fields": sorted(set(hallucinated)),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "hallucination_rate": round(len(set(hallucinated)) / predicted, 4) if predicted else 0.0,
        "health_recall": round(health_recall, 4) if health_recall is not None else None,
    }


def question_count(text: str) -> int:
    return text.count("?") + len(re.findall(r"(?:나요|까요|세요|습니까|니)\s*[.!]?\s*$", text.strip()))


def score_conversation(events: list[dict[str, Any]]) -> dict[str, Any]:
    assistant = [e for e in events if e.get("speaker") == "assistant"]
    user = [e for e in events if e.get("speaker") == "user"]
    question_counts = [question_count(str(e.get("text") or "")) for e in assistant]
    asked_topics = [
        str(e.get("state_after", {}).get("last_asked_topic_field") or "").strip()
        for e in assistant
    ]
    asked_topics = [t for t in asked_topics if t]
    repeated = sum(count - 1 for count in Counter(asked_topics).values() if count > 1)
    total_questions = sum(question_counts)
    return {
        "total_turns": len(events),
        "user_turns": len(user),
        "assistant_turns": len(assistant),
        "question_turns": sum(1 for count in question_counts if count),
        "question_rate": round(sum(1 for count in question_counts if count) / len(assistant), 4) if assistant else 0.0,
        "question_limit_violations": sum(1 for count in question_counts if count > 1),
        "question_limit_violation_rate": round(sum(1 for count in question_counts if count > 1) / len(assistant), 4) if assistant else 0.0,
        "semantic_repeat_count": repeated,
        "semantic_repeat_rate": round(repeated / total_questions, 4) if total_questions else 0.0,
    }


def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric = (
        "profile_f1", "profile_precision", "profile_recall", "hallucination_rate",
        "question_rate", "question_limit_violation_rate", "semantic_repeat_rate",
        "trust", "ease", "frustration",
    )
    summary: dict[str, Any] = {"runs": len(rows)}
    for key in numeric:
        values = [float(r[key]) for r in rows if r.get(key) not in (None, "")]
        if values:
            summary[key] = {
                "mean": round(sum(values) / len(values), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
            }
    scored_goals = [r for r in rows if r.get("goal_status") not in (None, "", "not_scored")]
    summary["goal_completion_rate"] = round(
        sum(r.get("goal_status") == "achieved" for r in scored_goals) / len(scored_goals), 4
    ) if scored_goals else None
    summary["goal_scored_runs"] = len(scored_goals)
    return summary
