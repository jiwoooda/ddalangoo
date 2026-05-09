from app.mock_data.addresses import MOCK_ADDRESSES
from typing import Optional, List

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
