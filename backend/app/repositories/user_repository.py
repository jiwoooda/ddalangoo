from app.mock_data.users import MOCK_USERS
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

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


def _user_to_dict(user: User) -> dict:
    """ORM User를 기존 서비스가 쓰는 dict 형태로 변환한다."""
    return {
        "id": user.id,
        "name": user.name,
        "phone_number": user.phone_number,
        "age_group": user.age_group,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


async def get_user_by_id_db(db: AsyncSession, user_id: int) -> Optional[dict]:
    """DB에서 사용자를 조회한다. 로컬 전환 단계에서는 mock 사용자를 DB에 1회 시드한다."""
    user = await db.get(User, user_id)
    if user:
        return _user_to_dict(user)

    # MVP 전환 단계: 기존 프론트가 userId=1을 보내므로 mock 사용자를 DB에 자동 시드한다.
    mock_user = get_user_by_id(user_id)
    if not mock_user:
        return None

    user = User(
        id=mock_user["id"],
        name=mock_user.get("name") or "사용자",
        phone_number=mock_user.get("phone_number"),
        age_group=mock_user.get("age_group"),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _user_to_dict(user)
