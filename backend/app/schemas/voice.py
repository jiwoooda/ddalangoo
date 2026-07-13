from pydantic import BaseModel
from typing import Any, Optional


class SttResponse(BaseModel):
    transcript: str


class TurnDetectionRequest(BaseModel):
    transcript: str
    partialTranscript: Optional[str] = None
    step: Optional[str] = None
    continuationCount: int = 0


class TurnDetectionResponse(BaseModel):
    result: str
    mergedTranscript: str
    reason: Optional[str] = None
    shouldAskClarification: bool = False


class TtsRequest(BaseModel):
    text: str


class TtsSegment(BaseModel):
    text: str
    durationMs: int


class TtsResponse(BaseModel):
    audioBase64: str
    mimeType: str
    segments: list[TtsSegment] | None = None
    totalDurationMs: int | None = None
    voiceTimeline: dict[str, Any] | None = None


class SttErrorDetail(BaseModel):
    code: str
    message: str


class SttErrorResponse(BaseModel):
    error: SttErrorDetail
