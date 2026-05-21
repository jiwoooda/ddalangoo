from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class BackendLatencyContext:
    session_id: str
    request_id: str
    turn_index: int
    mode: str = "TEXT_AGENT_ONLY"
    timestamps: dict[str, int] = field(default_factory=dict)

    def mark(self, key: str) -> None:
        self.timestamps[key] = _now_ms()

    def to_log(self) -> dict[str, Any]:
        return {
            "event": "backend_latency_turn",
            "session_id": self.session_id,
            "request_id": self.request_id,
            "turn_index": self.turn_index,
            "mode": self.mode,
            "backend_request_received": self._iso("backend_request_received"),
            "agent_start": self._iso("agent_start"),
            "agent_end": self._iso("agent_end"),
            "backend_response_sent": self._iso("backend_response_sent"),
            "agent_processing_ms": self._diff("agent_start", "agent_end"),
            "backend_processing_ms": self._diff(
                "backend_request_received",
                "backend_response_sent",
            ),
        }

    def _diff(self, start: str, end: str) -> int | None:
        start_ms = self.timestamps.get(start)
        end_ms = self.timestamps.get(end)
        if start_ms is None or end_ms is None:
            return None
        return end_ms - start_ms

    def _iso(self, key: str) -> str | None:
        value = self.timestamps.get(key)
        if value is None:
            return None
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def latency_context_from_headers(headers: dict[str, str]) -> BackendLatencyContext:
    session_id = headers.get("x-latency-session-id") or f"session-{uuid.uuid4()}"
    request_id = headers.get("x-latency-request-id") or f"request-{uuid.uuid4()}"
    turn_index = int(headers.get("x-latency-turn-index") or "0")
    context = BackendLatencyContext(
        session_id=session_id,
        request_id=request_id,
        turn_index=turn_index,
    )
    context.mark("backend_request_received")
    return context


def emit_latency_log(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


FASTAPI_EXAMPLE = """
from fastapi import APIRouter, Request
from .latency_logger import emit_latency_log, latency_context_from_headers

router = APIRouter()

@router.post("/api/agent/shopping-requests")
async def start_shopping(request: Request, body: ShoppingRequest):
    latency = latency_context_from_headers(dict(request.headers))
    latency.mark("agent_start")
    response = await agent_service.start_shopping(body)
    latency.mark("agent_end")
    latency.mark("backend_response_sent")
    emit_latency_log(latency.to_log())
    return response

@router.post("/api/agent/conversations/{conversation_id}/messages")
async def send_message(conversation_id: int, request: Request, body: MessageRequest):
    latency = latency_context_from_headers(dict(request.headers))
    latency.mark("agent_start")
    response = await agent_service.send_message(conversation_id, body)
    latency.mark("agent_end")
    latency.mark("backend_response_sent")
    emit_latency_log(latency.to_log())
    return response
"""
