from evals.smalltalk_population.metrics import (
    aggregate_rows,
    question_count,
    score_conversation,
    score_profile,
)
from evals.smalltalk_population.reporting import build_detailed_report, write_reports


def test_profile_metrics_distinguish_correct_missed_wrong_and_hallucinated():
    scored = score_profile(
        {
            "household_size": 1,
            "value_priority": "품질·브랜드",
            "favorite_foods": ["불고기", "김치"],
            "usual_order_platform": "쿠팡",
        },
        {
            "household_size": 1,
            "value_priority": "가성비",
            "favorite_foods": ["불고기"],
            "health_notes": ["당뇨"],
        },
        hidden_fields=["usual_order_platform"],
    )
    assert set(scored["correct_fields"]) == {"household_size", "favorite_foods"}
    assert scored["wrong_fields"] == ["value_priority"]
    assert scored["missed_fields"] == ["health_notes"]
    assert scored["hallucinated_fields"] == ["usual_order_platform"]
    assert scored["precision"] == 0.5
    assert scored["recall"] == 0.5


def test_unspoken_ground_truth_is_not_counted_as_missed():
    scored = score_profile({}, {}, hidden_fields=["health_notes"])
    assert scored["recall"] == 1.0
    assert scored["missed_fields"] == []


def test_conversation_metrics_count_question_limit_and_semantic_repeat():
    events = [
        {"speaker": "assistant", "text": "안녕하세요? 성함이 어떻게 되세요?", "state_after": {"last_asked_topic_field": "preferred_name"}},
        {"speaker": "user", "text": "김영숙이유"},
        {"speaker": "assistant", "text": "어떤 이름으로 불러드릴까요?", "state_after": {"last_asked_topic_field": "preferred_name"}},
    ]
    scored = score_conversation(events)
    assert question_count(events[0]["text"]) >= 2
    assert scored["question_limit_violations"] == 1
    assert scored["semantic_repeat_count"] == 1


def test_aggregate_rows_reports_mean_and_goal_rate():
    result = aggregate_rows([
        {"profile_f1": 1, "goal_status": "achieved", "trust": 5},
        {"profile_f1": 0.5, "goal_status": "failed", "trust": 3},
    ])
    assert result["profile_f1"]["mean"] == 0.75
    assert result["trust"]["mean"] == 4
    assert result["goal_completion_rate"] == 0.5


def test_unscored_goals_are_not_reported_as_failures():
    result = aggregate_rows([{"profile_f1": 1, "goal_status": "not_scored"}])
    assert result["goal_completion_rate"] is None
    assert result["goal_scored_runs"] == 0


def test_detailed_report_groups_and_writes_markdown(tmp_path):
    rows = [{
        "run_id": "P01-S1-R1", "persona_id": "P01", "scenario_id": "exploratory",
        "dialect": "표준 구어체", "profile_f1": 0.95, "hallucination_rate": 0,
        "health_recall": "", "question_limit_violation_rate": 0,
        "semantic_repeat_rate": 0, "trust": 4.5, "ease": 4, "frustration": 1,
        "goal_status": "achieved", "goal_reasoning": "", "error_type": "",
    }]
    config = {"experiment_id": "test", "model": "gpt", "judge": True, "planned_runs": 1}
    report = write_reports(tmp_path, rows, config)
    assert report["acceptance_thresholds"]["profile_f1"]["status"] == "PASS"
    assert report["by_scenario"][0]["scenario_id"] == "exploratory"
    assert (tmp_path / "detailed_report.md").is_file()
    assert (tmp_path / "detailed_report.json").is_file()
