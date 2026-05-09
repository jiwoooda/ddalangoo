from fastapi import APIRouter
from app.schemas.recommendation import RecommendationResponse
from app.services import recommendation_service

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

@router.get("/{recommendationId}", response_model=RecommendationResponse)
def get_recommendation(recommendationId: int):
    return recommendation_service.get_recommendation(recommendationId)
