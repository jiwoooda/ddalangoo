from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mock_data.users import MOCK_USERS
from app.models.user import User


# ── Mock(동기) 헬퍼 ──────────────────────────────────────────────────────────

def get_user_by_id(user_id: int) -> Optional[dict]:
    return next((u for u in MOCK_USERS if u["id"] == user_id), None)


def create_user(data: dict) -> dict:
    new_id = max(u["id"] for u in MOCK_USERS) + 1
    user = {"id": new_id, "is_active": True, **data}
    MOCK_USERS.append(user)
    return user


def update_user(user_id: int, data: dict) -> Optional[dict]:
    user = get_user_by_id(user_id)
    if not user:
        return None
    user.update({k: v for k, v in data.items() if v is not None})
    return user


# ── ORM → dict 변환 ──────────────────────────────────────────────────────────

def _user_to_dict(user: User) -> dict:
    """ORM User 인스턴스를 서비스 레이어가 쓰는 dict 형태로 변환한다."""
    return {
        "id": user.id,
        "name": user.name,
        "phone_number": user.phone_number or "",
        "age_group": user.age_group,
        "gender": user.gender,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


# ── DB(비동기) 함수 ───────────────────────────────────────────────────────────

async def get_user_by_id_db(db: AsyncSession, user_id: int) -> Optional[dict]:
    """DB에서 userId로 사용자를 조회한다.

    전환 단계 호환: DB에 없고 mock 데이터에 있으면 DB에 1회 시드한다.
    실제 가입 사용자가 생기면 mock 시드 분기는 자연스럽게 사용되지 않는다.
    """
    user = await db.get(User, user_id)
    if user:
        return _user_to_dict(user)

    # 전환 단계 호환 — mock 사용자를 DB에 자동 시드
    mock_user = get_user_by_id(user_id)
    if not mock_user:
        return None

    existing = await get_user_by_phone_db(db, mock_user.get("phone_number") or "")
    if existing:
        return existing

    user = User(
        id=mock_user["id"],
        name=mock_user.get("name") or "사용자",
        phone_number=mock_user.get("phone_number"),
        age_group=mock_user.get("age_group"),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _user_to_dict(user)


async def get_user_by_phone_db(db: AsyncSession, phone_number: str) -> Optional[dict]:
    """전화번호로 사용자를 조회한다 (로그인 / 중복 체크에 사용)."""
    if not phone_number:
        return None
    result = await db.execute(
        select(User).where(User.phone_number == phone_number)
    )
    user = result.scalar_one_or_none()
    return _user_to_dict(user) if user else None


async def create_user_db(db: AsyncSession, data: dict) -> dict:
    """DB에 사용자를 생성하고 저장한다.

    data 키: name, phone_number, age_group, password_hash (모두 선택)
    """
    user = User(
        name=data["name"],
        phone_number=data.get("phone_number") or None,
        age_group=data.get("age_group") or None,
        gender=data.get("gender") or None,
        password_hash=data.get("password_hash") or None,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _user_to_dict(user)


async def update_last_login_db(db: AsyncSession, user_id: int) -> None:
    """로그인 성공 시 last_login_at을 갱신한다."""
    user = await db.get(User, user_id)
    if user:
        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()
