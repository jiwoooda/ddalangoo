"""VIVID bridge의 기존 /chat 및 OpenAI-compatible adapter 회귀 테스트."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import vivid_bridge as bridge


class _State:
    def __init__(self, values: dict):
        self.values = values


class FakeGraph:
    """LLM 없이 bridge의 session/formatting 계약만 검증하는 최소 graph."""

    def __init__(self):
        self.states: dict[str, dict] = {}
        self.processed: list[tuple[str, str]] = []
        self.fail_next = False

    @staticmethod
    def _thread(config: dict) -> str:
        return config["configurable"]["thread_id"]

    def invoke(self, value, config):
        thread = self._thread(config)
        if value is not None:
            state = dict(value)
            state["messages"] = [{"role": "assistant", "content": "안녕하세요, 딸랑구예요."}]
            state["stage"] = "idle"
            self.states[thread] = state
            return state

        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("secret provider failure")
        state = self.states[thread]
        user_message = state["messages"][-1]["content"]
        state["messages"].append({"role": "assistant", "content": f"처리됨: {user_message}"})
        state["stage"] = "searching"
        self.processed.append((thread, user_message))
        return state

    def update_state(self, config, update):
        self.states[self._thread(config)]["messages"].extend(update["messages"])

    def get_state(self, config):
        return _State(self.states[self._thread(config)])


@pytest.fixture
def client(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(bridge, "_graph", fake)
    monkeypatch.setattr(bridge, "_BRIDGE_TOKEN", None)
    bridge._known_sessions.clear()
    with TestClient(bridge.app) as test_client:
        yield test_client, fake
    bridge._known_sessions.clear()


def _completion(message: str, **extra) -> dict:
    return {
        "model": "ddalangoo",
        "messages": [{"role": "user", "content": message}],
        **extra,
    }


def test_legacy_chat_keeps_greeting_then_reuses_session(client):
    test_client, fake = client
    session_id = f"legacy-{uuid.uuid4().hex}"

    first = test_client.post("/chat", json={"message": "우유 추천해줘", "session_id": session_id})
    assert first.status_code == 200
    assert first.json() == {
        "session_id": session_id,
        "reply": "안녕하세요, 딸랑구예요.",
        "stage": "idle",
    }
    assert fake.processed == []

    second = test_client.post("/chat", json={"message": "우유 추천해줘", "session_id": session_id})
    assert second.status_code == 200
    assert second.json() == {
        "session_id": session_id,
        "reply": "처리됨: 우유 추천해줘",
        "stage": "searching",
    }
    assert fake.processed == [(session_id, "우유 추천해줘")]


def test_openai_first_request_processes_user_and_has_compatible_shape(client):
    test_client, fake = client
    response = test_client.post("/v1/chat/completions", json=_completion("우유 추천해줘"))

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "처리됨: 우유 추천해줘"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["session_id"].startswith("vivid-")
    assert fake.processed == [(body["session_id"], "우유 추천해줘")]


def test_openai_session_id_continues_and_missing_id_creates_new_session(client):
    test_client, fake = client
    first = test_client.post("/v1/chat/completions", json=_completion("첫 질문")).json()
    session_id = first["session_id"]

    second = test_client.post(
        "/v1/chat/completions", json=_completion("후속 질문", session_id=session_id)
    ).json()
    third = test_client.post("/v1/chat/completions", json=_completion("새 질문")).json()

    assert second["session_id"] == session_id
    assert second["choices"][0]["message"]["content"] == "처리됨: 후속 질문"
    assert third["session_id"] != session_id
    assert [message for _, message in fake.processed] == ["첫 질문", "후속 질문", "새 질문"]


def test_openai_history_uses_only_last_user_message(client):
    test_client, fake = client
    response = test_client.post(
        "/v1/chat/completions",
        json={
            "model": "ddalangoo",
            "messages": [
                {"role": "system", "content": "외부 지시"},
                {"role": "user", "content": "과거 질문"},
                {"role": "assistant", "content": "과거 답변"},
                {"role": "user", "content": "마지막 질문"},
            ],
        },
    )

    assert response.status_code == 200
    assert fake.processed[0][1] == "마지막 질문"


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"model": "ddalangoo", "messages": []}, 400, "invalid_messages"),
        ({"model": "ddalangoo", "messages": [{"role": "assistant", "content": "답"}]}, 400, "missing_user_message"),
        ({"model": "other", "messages": [{"role": "user", "content": "질문"}]}, 404, "model_not_found"),
        ({"model": "ddalangoo", "messages": [{"role": "user", "content": "질문"}], "stream": True}, 400, "unsupported_parameter"),
    ],
)
def test_openai_validation_errors(client, payload, status, code):
    test_client, _ = client
    response = test_client.post("/v1/chat/completions", json=payload)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_models_and_auth_reuse_existing_token_policy(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(bridge, "_BRIDGE_TOKEN", "token-123")

    missing = test_client.get("/v1/models")
    wrong = test_client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
    valid = test_client.get("/v1/models", headers={"Authorization": "Bearer token-123"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["error"]["code"] == "invalid_api_key"
    assert valid.status_code == 200
    assert valid.json() == {
        "object": "list",
        "data": [{"id": "ddalangoo", "object": "model", "owned_by": "ddalangoo"}],
    }


def test_openai_agent_error_hides_internal_detail(client):
    test_client, fake = client
    fake.fail_next = True
    response = test_client.post("/v1/chat/completions", json=_completion("실패 요청"))

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "agent_error"
    assert "secret provider failure" not in response.text
