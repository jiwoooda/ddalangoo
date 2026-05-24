from pydantic import BaseModel
from typing import Optional, List


class ExternalApiLogItem(BaseModel):
    logId: int
    userId: Optional[int] = None
    conversationId: Optional[int] = None
    provider: str
    apiName: str
    statusCode: Optional[int] = None
    success: bool
    requestSummary: Optional[str] = None
    responseSummary: Optional[str] = None
    errorMessage: Optional[str] = None
    createdAt: str


class ExternalApiLogResponse(BaseModel):
    logs: List[ExternalApiLogItem]
