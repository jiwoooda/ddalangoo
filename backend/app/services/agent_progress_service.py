import asyncio
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket
else:
    WebSocket = Any


_latest_payload: dict[str, dict[str, Any]] = {}
_connections: dict[str, list[tuple[WebSocket, asyncio.AbstractEventLoop]]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_payload(channel_id: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault("type", "agent_progress")
    normalized.setdefault("channelId", channel_id)
    normalized.setdefault("updatedAt", _now_iso())
    return normalized


def get_latest_payload(channel_id: str) -> dict[str, Any] | None:
    return _latest_payload.get(channel_id)


async def connect(channel_id: str, websocket: WebSocket) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()
    _connections.setdefault(channel_id, []).append((websocket, loop))

    latest = get_latest_payload(channel_id)
    if latest:
        await websocket.send_json(_normalize_payload(channel_id, latest))


def disconnect(channel_id: str, websocket: WebSocket) -> None:
    sockets = _connections.get(channel_id, [])
    _connections[channel_id] = [
        item for item in sockets if item[0] is not websocket
    ]
    if not _connections[channel_id]:
        _connections.pop(channel_id, None)


async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    await websocket.send_json(payload)


def emit_progress(channel_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_payload(channel_id, payload)
    _latest_payload[channel_id] = normalized

    stale: list[WebSocket] = []
    for websocket, loop in list(_connections.get(channel_id, [])):
        try:
            asyncio.run_coroutine_threadsafe(_send_json(websocket, normalized), loop)
        except Exception:
            stale.append(websocket)

    for websocket in stale:
        disconnect(channel_id, websocket)

    return normalized


def clear_progress(channel_id: str) -> None:
    _latest_payload.pop(channel_id, None)
