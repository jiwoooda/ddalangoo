import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket
else:
    WebSocket = Any


_latest_status: dict[int, dict[str, Any]] = {}
_latest_screenshot: dict[int, bytes] = {}
_connections: dict[int, list[tuple[WebSocket, asyncio.AbstractEventLoop]]] = {}
_SCREENSHOT_DIR = Path("logs") / "webview_progress"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _screenshot_url(conversation_id: int) -> str:
    return f"/api/agent/conversations/{conversation_id}/webview/screenshot"


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "webview"


def _save_debug_screenshot(conversation_id: int, step: str, screenshot_bytes: bytes) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    directory = _SCREENSHOT_DIR / str(conversation_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{timestamp}_{_safe_name(step)}.jpg"
    path.write_bytes(screenshot_bytes)
    return str(path)


def get_latest_status(conversation_id: int) -> dict[str, Any] | None:
    return _latest_status.get(conversation_id)


def get_status_or_default(conversation_id: int) -> dict[str, Any]:
    latest_status = get_latest_status(conversation_id)
    if latest_status:
        return latest_status

    # 아직 웹뷰 작업이 시작되지 않았어도 프론트 계약 필드는 항상 내려준다.
    return {
        "type": "webview_progress",
        "conversationId": conversation_id,
        "flow": "unknown",
        "step": "not_started",
        "message": "웹뷰 진행을 기다리고 있어요.",
        "status": "waiting",
        "screenshotUrl": _screenshot_url(conversation_id),
        "updatedAt": _now_iso(),
    }


def get_latest_screenshot(conversation_id: int) -> bytes | None:
    return _latest_screenshot.get(conversation_id)


async def connect(conversation_id: int, websocket: WebSocket) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()
    _connections.setdefault(conversation_id, []).append((websocket, loop))

    latest = get_latest_status(conversation_id)
    if latest:
        await websocket.send_json(latest)


def disconnect(conversation_id: int, websocket: WebSocket) -> None:
    sockets = _connections.get(conversation_id, [])
    _connections[conversation_id] = [
        item for item in sockets if item[0] is not websocket
    ]
    if not _connections[conversation_id]:
        _connections.pop(conversation_id, None)


async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    await websocket.send_json(payload)


def emit_progress(
    conversation_id: int,
    *,
    step: str,
    message: str,
    flow: str | None = None,
    status: str = "running",
    screenshot_bytes: bytes | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    screenshot_path = None
    if screenshot_bytes:
        _latest_screenshot[conversation_id] = screenshot_bytes
        screenshot_path = _save_debug_screenshot(conversation_id, step, screenshot_bytes)

    print(
        "[webview_progress]",
        conversation_id,
        step,
        message,
        f"screenshot={bool(screenshot_bytes)}",
        f"path={screenshot_path}" if screenshot_path else "",
    )

    payload: dict[str, Any] = {
        "type": "webview_progress",
        "conversationId": conversation_id,
        "step": step,
        "message": message,
        "status": status,
        "updatedAt": _now_iso(),
    }
    if flow:
        payload["flow"] = flow
    # 프론트는 progress 표시 중 항상 같은 screenshot endpoint를 폴링할 수 있다.
    # 아직 캡처가 없으면 endpoint가 204를 반환하고, 캡처가 생기면 같은 URL에서 이미지를 내려준다.
    payload["screenshotUrl"] = _screenshot_url(conversation_id)
    if screenshot_path:
        payload["debugScreenshotPath"] = screenshot_path
    if meta:
        payload["meta"] = meta

    _latest_status[conversation_id] = payload

    stale: list[WebSocket] = []
    for websocket, loop in list(_connections.get(conversation_id, [])):
        try:
            asyncio.run_coroutine_threadsafe(_send_json(websocket, payload), loop)
        except Exception:
            stale.append(websocket)

    for websocket in stale:
        disconnect(conversation_id, websocket)

    return payload


def clear_progress(conversation_id: int) -> None:
    _latest_status.pop(conversation_id, None)
    _latest_screenshot.pop(conversation_id, None)
