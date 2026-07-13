from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from app.services import dev_service, voice_timeline_dashboard_service
from app.schemas.cart import SampleResponse
from app.schemas.dev import (
    VoiceTimelineIngestRequest,
    VoiceTimelineIngestResponse,
)
from pydantic import BaseModel
from typing import Optional

class SampleHistoryRequest(BaseModel):
    userId: Optional[int] = None

router = APIRouter(prefix="/dev", tags=["Dev"])

@router.post("/sample-products", response_model=SampleResponse)
def create_sample_products():
    return dev_service.get_sample_products()

@router.post("/sample-purchase-histories", response_model=SampleResponse)
def create_sample_purchase_histories(req: SampleHistoryRequest):
    return dev_service.get_sample_purchase_histories(user_id=req.userId)


@router.post(
    "/voice-timeline/ingest",
    response_model=VoiceTimelineIngestResponse,
)
def ingest_voice_timeline_log(req: VoiceTimelineIngestRequest):
    voice_timeline_dashboard_service.append_frontend_log_line(
        req.fileName,
        req.jsonLine,
    )
    return VoiceTimelineIngestResponse(
        accepted=True,
        fileName=req.fileName,
        byteCount=len(req.jsonLine.encode("utf-8")),
    )


@router.get("/voice-timeline/dashboard")
def voice_timeline_dashboard():
    return FileResponse(
        voice_timeline_dashboard_service.get_dashboard_html_path(),
        media_type="text/html",
    )


@router.get("/voice-timeline/dashboard-data")
def voice_timeline_dashboard_data(
    eventLimit: int = Query(default=300, ge=50, le=1000),
    turnLimit: int = Query(default=120, ge=20, le=500),
):
    return voice_timeline_dashboard_service.get_voice_timeline_dashboard_data(
        event_limit=eventLimit,
        turn_limit=turnLimit,
    )
