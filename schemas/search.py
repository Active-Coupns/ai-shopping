from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Literal, Optional

class SearchRequest(BaseModel):
    query: str = Field(default="deals", description="E-commerce search query")
    country: Optional[str] = Field(default="US", description="Target country code (US or IN)")
    user_id: Optional[str] = Field(default=None, description="Optional end-user identifier")
    page: Optional[int] = Field(default=1, description="Page index")

    @field_validator("country", mode="before")
    @classmethod
    def validate_country(cls, v: Any) -> str:
        if not v:
            return "US"
        v_str = str(v).upper().strip()
        if v_str not in ("US", "IN"):
            return "US"
        return v_str

class ProductCuration(BaseModel):
    title: str = Field(..., description="Name/title of the product")
    price: float = Field(..., description="Product price in USD or INR")
    original_url: str = Field(..., description="Original product details link")
    affiliate_url: str = Field(..., description="White-labeled affiliate redirected link")
    source: str = Field(..., description="E-commerce store identifier (e.g., Amazon, Walmart, Flipkart)")
    formatted_specs: Dict[str, Any] = Field(default_factory=dict, description="Key specifications extracted from product data")
    why_it_fits_you: str = Field(..., description="A curated 2-sentence reasoning explaining why this fits the search query")
    coupon_code: str = Field(default="None", description="Manual or automatic coupon code")
    coupon_description: str = Field(default="No Coupon Available Today", description="Description of the coupon offer")
    coupon_status: str = Field(default="No Coupon Available Today", description="Status of the coupon waterfall")
    reveal_url: str = Field(default="", description="The URL endpoint to reveal coupon and redirect affiliate session")
    image_url: Optional[str] = Field(default=None, description="HTTPS URL of the product image")
    thumbnail: Optional[str] = Field(default=None, description="HTTPS URL of the product thumbnail")

class Coupon(BaseModel):
    code: str = Field(..., description="Promo code or discount code")
    description: str = Field(..., description="Description of the offer")
    store: str = Field(..., description="The store where this coupon applies")

class SearchResponse(BaseModel):
    results: List[ProductCuration] = Field(..., description="Top 3 e-commerce matches curated by AI")
    coupons: List[Coupon] = Field(default_factory=list, description="Available deals & promo codes for the target country")
    credits_remaining: float = Field(..., description="Remaining credit balance in the client wallet")
    currency: str = Field(default="$", description="Currency symbol of the product prices (default is $)")
