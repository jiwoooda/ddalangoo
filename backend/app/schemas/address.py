from pydantic import BaseModel
from typing import Optional, List

class AddressItem(BaseModel):
    addressId: int
    addressLabel: Optional[str] = None
    recipientName: str
    recipientPhone: Optional[str] = None
    zipCode: Optional[str] = None
    addressLine1: str
    addressLine2: Optional[str] = None
    deliveryRequest: Optional[str] = None
    isDefault: bool

class AddressListResponse(BaseModel):
    userId: int
    addresses: List[AddressItem]

class AddressCreateRequest(BaseModel):
    addressLabel: Optional[str] = None
    recipientName: str
    recipientPhone: Optional[str] = None
    zipCode: Optional[str] = None
    addressLine1: str
    addressLine2: Optional[str] = None
    deliveryRequest: Optional[str] = None
    isDefault: bool = False

class AddressUpdateRequest(BaseModel):
    recipientName: Optional[str] = None
    recipientPhone: Optional[str] = None
    zipCode: Optional[str] = None
    addressLine1: Optional[str] = None
    addressLine2: Optional[str] = None
    deliveryRequest: Optional[str] = None

class AddressDefaultResponse(BaseModel):
    userId: int
    defaultAddressId: int
    message: str

class AddressDeleteResponse(BaseModel):
    message: str
