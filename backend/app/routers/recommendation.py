from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.recommendation import RecommendationResponse
from app.services import recommendation_service

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

@router.get("/{recommendationId}", response_model=RecommendationResponse)
async def get_recommendation(recommendationId: int, db: AsyncSession = Depends(get_db)):
    return await recommendation_service.get_recommendation_db(db, recommendationId)
