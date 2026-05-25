from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mock_data.addresses import MOCK_ADDRESSES
from app.models.address import UserAddress


def get_addresses_by_user_id(user_id: int) -> List[dict]:
    return [a for a in MOCK_ADDRESSES if a["user_id"] == user_id]

def get_address_by_id(address_id: int) -> Optional[dict]:
    return next((a for a in MOCK_ADDRESSES if a["id"] == address_id), None)

def create_address(data: dict) -> dict:
    new_id = max(a["id"] for a in MOCK_ADDRESSES) + 1
    addr = {"id": new_id, **data}
    MOCK_ADDRESSES.append(addr)
    return addr

def update_address(address_id: int, data: dict) -> Optional[dict]:
    addr = get_address_by_id(address_id)
    if not addr:
        return None
    addr.update({k: v for k, v in data.items() if v is not None})
    return addr

def set_default_address(user_id: int, address_id: int) -> Optional[dict]:
    for a in MOCK_ADDRESSES:
        if a["user_id"] == user_id:
            a["is_default"] = a["id"] == address_id
    return get_address_by_id(address_id)

def delete_address(address_id: int) -> bool:
    addr = get_address_by_id(address_id)
    if not addr:
        return False
    MOCK_ADDRESSES.remove(addr)
    return True

def get_default_address_by_user_id(user_id: int) -> Optional[dict]:
    return next((a for a in MOCK_ADDRESSES if a["user_id"] == user_id and a["is_default"]), None)


def _address_to_dict(address: UserAddress) -> dict:
    """ORM 배송지를 기존 service/repository가 쓰는 dict 형태로 변환한다."""
    return {
        "id": address.id,
        "user_id": address.user_id,
        "address_label": address.address_label,
        "recipient_name": address.recipient_name,
        "recipient_phone": address.recipient_phone,
        "zip_code": address.zip_code,
        "address_line1": address.address_line1,
        "address_line2": address.address_line2,
        "delivery_request": address.delivery_request,
        "is_default": address.is_default,
        "created_at": address.created_at,
        "updated_at": address.updated_at,
    }


async def get_default_address_by_user_id_db(
    db: AsyncSession,
    user_id: int,
) -> Optional[dict]:
    """DB에서 사용자의 기본 배송지를 조회한다."""
    result = await db.execute(
        select(UserAddress).where(
            UserAddress.user_id == user_id,
            UserAddress.is_default.is_(True),
        )
    )
    address = result.scalars().first()
    if not address:
        return None
    return _address_to_dict(address)
