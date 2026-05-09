from pydantic import BaseModel
from typing import Optional

class UserResponse(BaseModel):
    userId: int
    name: str
    phoneNumber: str
    ageGroup: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

class UserCreateRequest(BaseModel):
    name: str
    phoneNumber: Optional[str] = None
    ageGroup: Optional[str] = None

class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    phoneNumber: Optional[str] = None
    ageGroup: Optional[str] = None
