import threading
import time
from copy import deepcopy
from typing import Any


class PlaywrightStreamService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[int, dict[str, Any]] = {}
        self._versions: dict[int, int] = {}

    def reset(self, conversation_id: int) -> None:
        with self._lock:
            self._versions[conversation_id] = 0
            self._events[conversation_id] = {
                "type": "status",
                "status": "idle",
                "message": "스트림을 준비 중이에요.",
                "stage": "idle",
                "version": 0,
                "timestamp": time.time(),
                "final": False,
                "imageBase64": None,
                "mimeType": None,
            }

    def publish(self, conversation_id: int, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            version = self._versions.get(conversation_id, 0) + 1
            payload = {
                **event,
                "version": version,
                "timestamp": time.time(),
            }
            self._versions[conversation_id] = version
            self._events[conversation_id] = payload
            return deepcopy(payload)

    def latest(self, conversation_id: int) -> dict[str, Any] | None:
        with self._lock:
            event = self._events.get(conversation_id)
            return deepcopy(event) if event else None

    def latest_version(self, conversation_id: int) -> int:
        with self._lock:
            return self._versions.get(conversation_id, 0)


playwright_stream_service = PlaywrightStreamService()
