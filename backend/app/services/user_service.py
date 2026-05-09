from app.repositories import user_repository
from app.schemas.user import UserResponse, UserCreateRequest, UserUpdateRequest
from fastapi import HTTPException
import datetime

def get_user(user_id: int) -> UserResponse:
    user = user_repository.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    return UserResponse(userId=user["id"], name=user["name"], phoneNumber=user["phone_number"],
                        ageGroup=user.get("age_group"),
                        createdAt=user.get("created_at"), updatedAt=user.get("updated_at"))

def create_user(req: UserCreateRequest) -> UserResponse:
    now = datetime.datetime.now().isoformat()
    user = user_repository.create_user({"name": req.name, "phone_number": req.phoneNumber or "",
                                         "age_group": req.ageGroup, "created_at": now, "updated_at": now})
    return UserResponse(userId=user["id"], name=user["name"], phoneNumber=user["phone_number"],
                        ageGroup=user.get("age_group"),
                        createdAt=user.get("created_at"), updatedAt=user.get("updated_at"))

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
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    return UserResponse(userId=user["id"], name=user["name"], phoneNumber=user["phone_number"],
                        ageGroup=user.get("age_group"),
                        createdAt=user.get("created_at"), updatedAt=user.get("updated_at"))
