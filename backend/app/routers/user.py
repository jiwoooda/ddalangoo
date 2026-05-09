from fastapi import APIRouter
from app.schemas.user import UserResponse, UserCreateRequest, UserUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/{userId}", response_model=UserResponse)
def get_user(userId: int):
    return user_service.get_user(userId)

@router.post("", response_model=UserResponse)
def create_user(req: UserCreateRequest):
    return user_service.create_user(req)

@router.patch("/{userId}", response_model=UserResponse)
def update_user(userId: int, req: UserUpdateRequest):
    return user_service.update_user(userId, req)
