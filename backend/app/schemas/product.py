from pydantic import BaseModel
from typing import Optional, List

class ProductOptionDetail(BaseModel):
    productOptionId: int
    optionName: str
    optionValue: str
    volume: Optional[str] = None
    additionalPrice: int = 0
    stockQuantity: Optional[int] = None
    isAvailable: bool = True

class ExternalMapping(BaseModel):
    platform: str
    mallName: Optional[str] = None
    productUrl: Optional[str] = None
    externalProductId: Optional[str] = None
    externalOptionId: Optional[str] = None

class ProductSummary(BaseModel):
    productId: int
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    subCategory: Optional[str] = None
    currentPrice: int
    rating: Optional[float] = None
    reviewCount: Optional[int] = None
    imageUrl: Optional[str] = None
    isAvailable: bool = True

class ProductListResponse(BaseModel):
    products: List[ProductSummary]

class ProductDetailResponse(BaseModel):
    productId: int
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    subCategory: Optional[str] = None
    description: Optional[str] = None
    imageUrl: Optional[str] = None
    currentPrice: int
    rating: Optional[float] = None
    reviewCount: Optional[int] = None
    isAvailable: bool = True
    options: List[ProductOptionDetail] = []
    externalMappings: List[ExternalMapping] = []

class ProductOptionsResponse(BaseModel):
    productId: int
    options: List[ProductOptionDetail]
