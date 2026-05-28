import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import user_repository
from app.schemas.user import (
    UserCreateRequest,
    UserLoginRequest,
    UserResponse,
    UserUpdateRequest,
    normalize_phone,
)


# ── 동기 헬퍼 (mock 기반 GET / PATCH — 기존 호환 유지) ─────────────────────────

def get_user(user_id: int) -> UserResponse:
    user = user_repository.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "USER_ERROR",
                "code": "USER_NOT_FOUND",
                "message": "사용자를 찾을 수 없습니다.",
            },
        )
    return _to_response(user)


def update_user(user_id: int, req: UserUpdateRequest) -> UserResponse:
    data = {"updated_at": datetime.datetime.now().isoformat()}
    if req.name is not None:
        data["name"] = req.name
    if req.phoneNumber is not None:
        data["phone_number"] = req.phoneNumber
    if req.ageGroup is not None:
        data["age_group"] = req.ageGroup
    user = user_repository.update_user(user_id, data)
    if not user:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "USER_ERROR",
                "code": "USER_NOT_FOUND",
                "message": "사용자를 찾을 수 없습니다.",
            },
        )
    return _to_response(user)


# ── 비동기 (DB 기반 POST /users, POST /users/login) ──────────────────────────

async def create_user_db(db: AsyncSession, req: UserCreateRequest) -> UserResponse:
    """전화번호 기반 회원가입.

    동일 전화번호가 이미 있으면 409 Conflict를 반환한다.
    전화번호가 없으면 이름만으로 계정을 만든다 (데모/테스트용).
    """
    name = req.name.strip()
    phone = normalize_phone(req.phoneNumber)

    if phone:
        existing = await user_repository.get_user_by_phone_db(db, phone)
        if existing:
            raise HTTPException(
                status_code=409,
                detail={
                    "category": "USER_ERROR",
                    "code": "PHONE_ALREADY_EXISTS",
                    "message": "이미 가입된 전화번호입니다. 로그인해주세요.",
                },
            )

    user = await user_repository.create_user_db(
        db,
        {
            "name": name,
            "phone_number": phone,
            "age_group": req.ageGroup,
            "gender": req.gender,
        },
    )
    return _to_response(user)


async def get_user_db(db: AsyncSession, user_id: int) -> UserResponse:
    """DB에서 userId로 사용자를 조회한다.

    POST /users가 DB에 저장한 사용자를 GET /users/{id}가 바로 찾을 수 있어야 한다.
    """
    user = await user_repository.get_user_by_id_db(db, user_id)
    if not user:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "USER_ERROR",
                "code": "USER_NOT_FOUND",
                "message": "사용자를 찾을 수 없습니다.",
            },
        )
    return _to_response(user)


async def update_user_db(
    db: AsyncSession,
    user_id: int,
    req: UserUpdateRequest,
) -> UserResponse:
    """DB 사용자 정보를 수정한다."""
    data = {"updated_at": datetime.datetime.now(datetime.timezone.utc)}
    if req.name is not None:
        data["name"] = req.name
    if req.phoneNumber is not None:
        data["phone_number"] = normalize_phone(req.phoneNumber)
    if req.ageGroup is not None:
        data["age_group"] = req.ageGroup
    if req.gender is not None:
        data["gender"] = req.gender

    user = await user_repository.update_user_db(db, user_id, data)
    if not user:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "USER_ERROR",
                "code": "USER_NOT_FOUND",
                "message": "사용자를 찾을 수 없습니다.",
            },
        )
    return _to_response(user)


async def login_by_phone(db: AsyncSession, req: UserLoginRequest) -> UserResponse:
    """전화번호 기반 로그인.

    전화번호로 사용자를 찾아 반환한다. MVP에서는 비밀번호 검증 없이 전화번호만 확인한다.
    추후 password_hash가 설정된 경우 비밀번호 검증 로직을 여기에 추가한다.
    """
    phone = normalize_phone(req.resolved_phone)
    if not phone:
        raise HTTPException(
            status_code=422,
            detail={
                "category": "USER_ERROR",
                "code": "PHONE_REQUIRED",
                "message": "전화번호를 입력해주세요.",
            },
        )

    user = await user_repository.get_user_by_phone_db(db, phone)
    if not user:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "USER_ERROR",
                "code": "USER_NOT_FOUND",
                "message": "등록되지 않은 전화번호입니다. 먼저 회원가입해주세요.",
            },
        )

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=403,
            detail={
                "category": "USER_ERROR",
                "code": "USER_INACTIVE",
                "message": "비활성화된 계정입니다.",
            },
        )

    # 마지막 로그인 시각 갱신 (fire-and-forget, 실패해도 로그인은 성공)
    try:
        await user_repository.update_last_login_db(db, user["id"])
    except Exception:
        pass

    return _to_response(user)


# ── 공통 ──────────────────────────────────────────────────────────────────────

def _to_response(user: dict) -> UserResponse:
    created = user.get("created_at")
    updated = user.get("updated_at")
    return UserResponse(
        userId=user["id"],
        name=user["name"],
        phoneNumber=user.get("phone_number") or "",
        ageGroup=user.get("age_group"),
        gender=user.get("gender"),
        createdAt=str(created) if created else None,
        updatedAt=str(updated) if updated else None,
    )
