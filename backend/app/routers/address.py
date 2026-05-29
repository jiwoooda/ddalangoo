from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.address import AddressListResponse, AddressItem, AddressCreateRequest, AddressUpdateRequest, AddressDefaultResponse, AddressDeleteResponse
from app.services import address_service

router = APIRouter(prefix="/users", tags=["Addresses"])

@router.get("/{userId}/addresses", response_model=AddressListResponse)
async def get_addresses(userId: int, db: AsyncSession = Depends(get_db)):
    return await address_service.get_addresses_db(db, userId)

@router.post("/{userId}/addresses", response_model=AddressItem)
async def create_address(userId: int, req: AddressCreateRequest, db: AsyncSession = Depends(get_db)):
    return await address_service.create_address_db(db, userId, req)

@router.patch("/{userId}/addresses/{addressId}", response_model=AddressItem)
async def update_address(userId: int, addressId: int, req: AddressUpdateRequest, db: AsyncSession = Depends(get_db)):
    return await address_service.update_address_db(db, userId, addressId, req)

@router.patch("/{userId}/addresses/{addressId}/default", response_model=AddressDefaultResponse)
async def set_default_address(userId: int, addressId: int, db: AsyncSession = Depends(get_db)):
    return await address_service.set_default_address_db(db, userId, addressId)

@router.delete("/{userId}/addresses/{addressId}", response_model=AddressDeleteResponse)
async def delete_address(userId: int, addressId: int, db: AsyncSession = Depends(get_db)):
    return await address_service.delete_address_db(db, userId, addressId)
