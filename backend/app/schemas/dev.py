from typing import Literal

from pydantic import BaseModel


class VoiceTimelineIngestRequest(BaseModel):
    fileName: Literal[
        "frontend_voice_timeline.jsonl",
        "frontend_latency_turns.jsonl",
    ]
    jsonLine: str


class VoiceTimelineIngestResponse(BaseModel):
    accepted: bool
    fileName: str
    byteCount: int
