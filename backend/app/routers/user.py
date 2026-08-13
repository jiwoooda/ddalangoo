from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.user import (
    UserCreateRequest,
    UserLoginRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.schemas.preference_report import PreferenceReportResponse
from app.services import preference_report_service, user_service

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
async def get_user(userId: int, db: AsyncSession = Depends(get_db)):
    """userId로 사용자 조회.

    회원가입/로그인은 DB 기반이므로 조회도 같은 DB를 봐야 한다.
    """
    return await user_service.get_user_db(db, userId)


@router.get("/{userId}/preference-report", response_model=PreferenceReportResponse)
async def get_preference_report(userId: int, db: AsyncSession = Depends(get_db)):
    """사용자 구매이력/선호도 캐시 기반 분석 리포트를 조회한다."""
    await user_service.get_user_db(db, userId)
    return await preference_report_service.get_preference_report_db(db, userId)


@router.patch("/{userId}", response_model=UserResponse)
async def update_user(
    userId: int,
    req: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """사용자 정보 수정.

    회원가입된 DB 사용자를 수정하고, 전환 단계 mock 사용자는 repository에서 DB에 시드한다.
    """
    return await user_service.update_user_db(db, userId, req)
