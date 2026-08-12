from pydantic import BaseModel
from typing import Optional


class SttResponse(BaseModel):
    transcript: str


class TtsRequest(BaseModel):
    text: str


class TtsResponse(BaseModel):
    audioBase64: str
    mimeType: str


class SttErrorDetail(BaseModel):
    code: str
    message: str


class SttErrorResponse(BaseModel):
    error: SttErrorDetail
