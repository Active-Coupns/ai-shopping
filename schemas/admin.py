from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class CreditUpdateRequest(BaseModel):
    client_id: int
    amount: float = Field(..., description="Amount of credits to add (positive) or deduct (negative)")

class KeyRevocationRequest(BaseModel):
    key: str = Field(..., description="The X-API-Key to revoke")

class KeyGenerationRequest(BaseModel):
    client_id: int

class UsageLogSummary(BaseModel):
    id: int
    endpoint: str
    country: Optional[str]
    credits_deducted: float
    timestamp: datetime
    response_status: int

class ClientMetrics(BaseModel):
    client_id: int
    client_name: str
    current_balance: float
    total_calls: int
    total_credits_spent: float
    api_key: Optional[str] = None
    api_key_active: bool = True
    last_active: Optional[datetime] = None

class AdminMetricsResponse(BaseModel):
    total_clients: int
    total_requests: int
    total_credits_deducted: float
    clients: List[ClientMetrics]
    recent_logs: List[UsageLogSummary]
