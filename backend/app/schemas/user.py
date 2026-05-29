import re
from pydantic import BaseModel
from typing import Optional


def normalize_phone(raw: str | None) -> str | None:
    """숫자만 추출 후 한국 휴대폰 형식으로 정규화한다.

    "01012345678" → "010-1234-5678"
    유효하지 않으면 None 반환.
    """
    if not raw:
        return None
    digits = re.sub(r"[^0-9]", "", raw)
    m = re.match(r"^(01[016789])(\d{3,4})(\d{4})$", digits)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


class UserResponse(BaseModel):
    userId: int
    name: str
    phoneNumber: str
    ageGroup: Optional[str] = None
    gender: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class UserCreateRequest(BaseModel):
    name: str
    phoneNumber: Optional[str] = None
    ageGroup: Optional[str] = None
    gender: Optional[str] = None


class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    phoneNumber: Optional[str] = None
    ageGroup: Optional[str] = None
    gender: Optional[str] = None


class UserLoginRequest(BaseModel):
    """전화번호 기반 로그인 요청.

    프론트엔드 UserRepository.login()이 보내는 필드명에 맞춘다.
    phone_number(snake_case)와 phoneNumber(camelCase) 모두 허용한다.
    """

    name: str
    phoneNumber: Optional[str] = None
    phone_number: Optional[str] = None

    @property
    def resolved_phone(self) -> str:
        """camelCase / snake_case 중 채워진 쪽을 반환한다."""
        return (self.phoneNumber or self.phone_number or "").strip()
