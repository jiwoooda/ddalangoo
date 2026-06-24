from pydantic import BaseModel
from typing import Optional


class SttResponse(BaseModel):
    transcript: str


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


class SttErrorDetail(BaseModel):
    code: str
    message: str


class SttErrorResponse(BaseModel):
    error: SttErrorDetail
