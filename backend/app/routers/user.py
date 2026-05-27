from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.user import (
    UserCreateRequest,
    UserLoginRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services import user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/login", response_model=UserResponse)
async def login(req: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """전화번호 기반 로그인.

    프론트엔드 UserRepository.login()이 호출하는 엔드포인트다.
    body: {name, phoneNumber} 또는 {name, phone_number}
    response: {userId, name, phoneNumber, ageGroup, createdAt, updatedAt}
    """
    return await user_service.login_by_phone(db, req)


@router.post("", response_model=UserResponse)
async def create_user(req: UserCreateRequest, db: AsyncSession = Depends(get_db)):
    """회원가입 — 전화번호 기반으로 DB에 사용자를 생성한다.

    동일 전화번호가 이미 존재하면 409를 반환한다.
    """
    return await user_service.create_user_db(db, req)


@router.get("/{userId}", response_model=UserResponse)
def get_user(userId: int):
    """userId로 사용자 조회 (mock 기반 — 전환 단계 호환용)."""
    return user_service.get_user(userId)


@router.patch("/{userId}", response_model=UserResponse)
def update_user(userId: int, req: UserUpdateRequest):
    """사용자 정보 수정 (mock 기반 — 전환 단계 호환용)."""
    return user_service.update_user(userId, req)
