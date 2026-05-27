from fastapi import APIRouter
from app.services import dev_service
from app.schemas.cart import SampleResponse
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
