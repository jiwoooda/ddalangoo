import langgraph.errors
from pathlib import Path
import pytest

if not hasattr(langgraph.errors, "NodeError"):
    class NodeError(Exception):
        pass
    langgraph.errors.NodeError = NodeError

from src.agents.smalltalk_agent import SmalltalkOutput, _build_merged_profile
from src.state.smalltalk_schema import AdditionalSignal, SmalltalkProfileSchema, validate_persisted_profile
from src.tools import db_client


def test_persisted_profile_rejects_invalid_enum():
    with pytest.raises(ValueError):
        validate_persisted_profile({"delivery_priority": "무조건 쿠팡"})


def test_profile_merge_deduplicates_notes_and_additional_signals(monkeypatch):
    monkeypatch.setattr(
        db_client,
        "get_profile",
        lambda user_id: {
            "household_notes": ["혼자 거주"],
            "additional_signals": [{"label": "포장 선호", "value": "소포장"}],
        },
    )
    result = SmalltalkOutput(
        reply="네",
        profile=SmalltalkProfileSchema(
            household_notes=["혼자 거주"],
            additional_signals=[AdditionalSignal(label="포장 선호", value="소포장")],
        ),
    )

    merged, changed = _build_merged_profile("1", result)

    assert changed is False
    assert merged["household_notes"] == ["혼자 거주"]
    assert merged["additional_signals"] == [{"label": "포장 선호", "value": "소포장"}]


def test_mock_purchase_invalidation_preserves_profile():
    user_id = "profile-preservation-test"
    db_client.save_profile(user_id, {"preferred_name": "철수", "onboarded_at": "now"}, mode="mock")
    db_client.save_general_preference(user_id, {"summary": "가성비"}, mode="mock")

    db_client.invalidate_purchase_derived_preferences(user_id, mode="mock")

    assert db_client.get_profile(user_id, mode="mock")["preferred_name"] == "철수"
    assert db_client.get_general_preference(user_id, mode="mock") is None


def test_repository_purchase_invalidation_does_not_delete_profile(monkeypatch):
    backend_root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(backend_root))
    from app.repositories import user_preference_repository as repository

    deleted = []
    monkeypatch.setattr(repository, "_can_try_database", lambda: True)
    monkeypatch.setattr(
        repository,
        "_delete_cache_rows",
        lambda user_id, preference_type=None, keyword_key=None: deleted.append(preference_type),
    )

    repository.invalidate_purchase_derived_preferences(7)

    assert deleted == ["general", "keyword"]
