from app.mock_data.users import MOCK_USERS
from typing import Optional

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
