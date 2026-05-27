from pydantic import BaseModel
from typing import Optional


class SttResponse(BaseModel):
    transcript: str


class SttErrorDetail(BaseModel):
    code: str
    message: str


class SttErrorResponse(BaseModel):
    error: SttErrorDetail
