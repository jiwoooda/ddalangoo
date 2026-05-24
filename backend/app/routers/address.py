from fastapi import APIRouter
from app.schemas.address import AddressListResponse, AddressItem, AddressCreateRequest, AddressUpdateRequest, AddressDefaultResponse, AddressDeleteResponse
from app.services import address_service

router = APIRouter(prefix="/users", tags=["Addresses"])

@router.get("/{userId}/addresses", response_model=AddressListResponse)
def get_addresses(userId: int):
    return address_service.get_addresses(userId)

@router.post("/{userId}/addresses", response_model=AddressItem)
def create_address(userId: int, req: AddressCreateRequest):
    return address_service.create_address(userId, req)

@router.patch("/{userId}/addresses/{addressId}", response_model=AddressItem)
def update_address(userId: int, addressId: int, req: AddressUpdateRequest):
    return address_service.update_address(userId, addressId, req)

@router.patch("/{userId}/addresses/{addressId}/default", response_model=AddressDefaultResponse)
def set_default_address(userId: int, addressId: int):
    return address_service.set_default_address(userId, addressId)

@router.delete("/{userId}/addresses/{addressId}", response_model=AddressDeleteResponse)
def delete_address(userId: int, addressId: int):
    return address_service.delete_address(userId, addressId)
