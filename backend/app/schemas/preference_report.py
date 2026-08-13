from pydantic import BaseModel


class PreferencePriceRange(BaseModel):
    average: int | None = None
    min: int | None = None
    max: int | None = None


class PreferenceReportResponse(BaseModel):
    userId: int
    hasData: bool
    interestKeywords: list[str]
    repurchaseProducts: list[str]
    preferredPlatforms: list[str]
    preferredBrands: list[str]
    priceRange: PreferencePriceRange | None = None
    summary: str | None = None
    computedAt: str | None = None
