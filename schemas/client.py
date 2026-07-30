from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import List, Optional

class ApiKeyBase(BaseModel):
    key: str
    is_active: bool

class ApiKeyResponse(ApiKeyBase):
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class WalletResponse(BaseModel):
    balance: float
    currency: str
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ClientCreate(BaseModel):
    name: str
    email: Optional[str] = None
    password: Optional[str] = None

class ClientResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    created_at: datetime
    wallet: Optional[WalletResponse] = None
    api_keys: List[ApiKeyResponse] = []

    model_config = ConfigDict(from_attributes=True)
