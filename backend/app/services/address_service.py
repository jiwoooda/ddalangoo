from app.repositories import address_repository, user_repository
from app.schemas.address import AddressItem, AddressListResponse, AddressCreateRequest, AddressUpdateRequest, AddressDefaultResponse, AddressDeleteResponse
from fastapi import HTTPException

def _to_item(a: dict) -> AddressItem:
    return AddressItem(
        addressId=a["id"], addressLabel=a.get("address_label"), recipientName=a["recipient_name"],
        recipientPhone=a.get("recipient_phone"), zipCode=a.get("zip_code"),
        addressLine1=a["address_line1"], addressLine2=a.get("address_line2"),
        deliveryRequest=a.get("delivery_request"), isDefault=a["is_default"],
    )

def get_addresses(user_id: int) -> AddressListResponse:
    if not user_repository.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    addrs = address_repository.get_addresses_by_user_id(user_id)
    return AddressListResponse(userId=user_id, addresses=[_to_item(a) for a in addrs])

def create_address(user_id: int, req: AddressCreateRequest) -> AddressItem:
    if not user_repository.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    data = {"user_id": user_id, "address_label": req.recipientName, "recipient_name": req.recipientName,
            "recipient_phone": req.recipientPhone, "zip_code": req.zipCode, "address_line1": req.addressLine1,
            "address_line2": req.addressLine2, "delivery_request": req.deliveryRequest, "is_default": req.isDefault}
    addr = address_repository.create_address(data)
    return _to_item(addr)

def update_address(user_id: int, address_id: int, req: AddressUpdateRequest) -> AddressItem:
    addr = address_repository.get_address_by_id(address_id)
    if not addr or addr["user_id"] != user_id:
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "ADDRESS_NOT_FOUND", "message": "주소를 찾을 수 없습니다."})
    data = {}
    if req.recipientName is not None: data["recipient_name"] = req.recipientName
    if req.recipientPhone is not None: data["recipient_phone"] = req.recipientPhone
    if req.zipCode is not None: data["zip_code"] = req.zipCode
    if req.addressLine1 is not None: data["address_line1"] = req.addressLine1
    if req.addressLine2 is not None: data["address_line2"] = req.addressLine2
    if req.deliveryRequest is not None: data["delivery_request"] = req.deliveryRequest
    updated = address_repository.update_address(address_id, data)
    return _to_item(updated)

def set_default_address(user_id: int, address_id: int) -> AddressDefaultResponse:
    addr = address_repository.get_address_by_id(address_id)
    if not addr or addr["user_id"] != user_id:
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "ADDRESS_NOT_FOUND", "message": "주소를 찾을 수 없습니다."})
    address_repository.set_default_address(user_id, address_id)
    return AddressDefaultResponse(userId=user_id, defaultAddressId=address_id, message="기본 배송지가 변경되었습니다.")

def delete_address(user_id: int, address_id: int) -> AddressDeleteResponse:
    addr = address_repository.get_address_by_id(address_id)
    if not addr or addr["user_id"] != user_id:
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "ADDRESS_NOT_FOUND", "message": "주소를 찾을 수 없습니다."})
    address_repository.delete_address(address_id)
    return AddressDeleteResponse(message="배송지가 삭제되었습니다.")
