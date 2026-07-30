from pydantic import BaseModel, Field
from typing import Optional, Literal

class DashboardLoginRequest(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None

class DashboardLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Literal["admin", "client"]
    client_name: str

class AffiliateTagUpdateRequest(BaseModel):
    store_name: Literal["Amazon", "Walmart", "Flipkart"]
    country: Literal["US", "IN"]
    affiliate_tag: str = Field(..., min_length=1, description="Custom affiliate tag string to inject")

class AffiliateConfigUpdateRequest(BaseModel):
    primary_strategy: Literal["cuelinks", "direct"]
    cuelinks_pub_id: Optional[str] = None
    amazon_tag: Optional[str] = None
    flipkart_tag: Optional[str] = None
    amazon_tag_in: Optional[str] = None
    amazon_tag_us: Optional[str] = None
    aggregator_network_name: Optional[str] = None
    aggregator_publisher_id: Optional[str] = None
    aggregator_url_template: Optional[str] = None
