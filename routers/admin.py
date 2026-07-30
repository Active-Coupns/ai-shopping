import secrets
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from config import settings
from models.client import Client
from models.api_key import ApiKey
from models.wallet import CreditWallet
from models.usage_log import UsageLog

from schemas.client import ClientCreate, ClientResponse, ApiKeyResponse
from schemas.admin import (
    CreditUpdateRequest,
    KeyRevocationRequest,
    KeyGenerationRequest,
    AdminMetricsResponse,
    ClientMetrics,
    UsageLogSummary
)

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])
logger = logging.getLogger("gateway.router.admin")

def verify_admin_token(x_admin_token: str = Header(..., alias="X-Admin-Token")):
    """Verifies that the incoming X-Admin-Token header matches the configured admin secret token."""
    if x_admin_token != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid Admin Credentials"
        )

@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED, summary="Create a new client with credit wallet & api key")
def create_client(
    payload: ClientCreate,
    db: Session = Depends(get_db),
    admin_auth: None = Depends(verify_admin_token)
):
    """Admin endpoint to register a new white-label tenant."""
    existing = db.query(Client).filter(Client.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Client with name '{payload.name}' already exists."
        )
        
    new_client = Client(
        name=payload.name,
        email=payload.email,
        password=payload.password
    )
    db.add(new_client)
    db.flush()
    
    new_wallet = CreditWallet(client_id=new_client.id, balance=100.0, currency="USD")
    db.add(new_wallet)
    
    generated_key = f"gw_{secrets.token_hex(16)}"
    new_key = ApiKey(client_id=new_client.id, key=generated_key, is_active=True)
    db.add(new_key)
    
    db.commit()
    db.refresh(new_client)
    return new_client

@router.post("/keys/generate", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED, summary="Generate an additional key for an existing client")
def generate_key(
    payload: KeyGenerationRequest,
    db: Session = Depends(get_db),
    admin_auth: None = Depends(verify_admin_token)
):
    """Generates a new active API key for the specified client ID."""
    client = db.query(Client).filter(Client.id == payload.client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client with ID {payload.client_id} not found"
        )
        
    generated_key = f"gw_{secrets.token_hex(16)}"
    new_key = ApiKey(client_id=client.id, key=generated_key, is_active=True)
    db.add(new_key)
    db.commit()
    db.refresh(new_key)
    return new_key

@router.post("/keys/revoke", summary="One-click Key Revocation / Kill Switch")
def revoke_key(
    payload: KeyRevocationRequest,
    db: Session = Depends(get_db),
    admin_auth: None = Depends(verify_admin_token)
):
    """Deactivates/Revokes a specific API key immediately, acting as a kill switch."""
    key_record = db.query(ApiKey).filter(ApiKey.key == payload.key).first()
    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found"
        )
        
    key_record.is_active = False
    db.commit()
    return {"status": "success", "message": "API Key has been successfully revoked."}

@router.post("/keys/activate", summary="Re-activate a revoked API Key")
def activate_key(
    payload: KeyRevocationRequest,
    db: Session = Depends(get_db),
    admin_auth: None = Depends(verify_admin_token)
):
    """Re-activates a revoked API key."""
    key_record = db.query(ApiKey).filter(ApiKey.key == payload.key).first()
    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found"
        )
        
    key_record.is_active = True
    db.commit()
    return {"status": "success", "message": "API Key has been successfully activated."}

@router.post("/credits/topup", summary="Add or deduct wallet credits")
def topup_credits(
    payload: CreditUpdateRequest,
    db: Session = Depends(get_db),
    admin_auth: None = Depends(verify_admin_token)
):
    """Modifies client credit wallet balances. Positive values add credits; negative values deduct."""
    client = db.query(Client).filter(Client.id == payload.client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client with ID {payload.client_id} not found."
        )
        
    wallet = client.wallet
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Client credit wallet not initialized."
        )
        
    wallet.balance += payload.amount
    if wallet.balance < 0.0:
        wallet.balance = 0.0
        
    db.commit()
    db.refresh(wallet)
    return {
        "status": "success",
        "client_name": client.name,
        "new_balance": wallet.balance,
        "currency": wallet.currency
    }

@router.get("/metrics", response_model=AdminMetricsResponse, summary="Retrieve Gateway usage and billing metrics")
def get_metrics(
    db: Session = Depends(get_db),
    admin_auth: None = Depends(verify_admin_token)
):
    """Fetches comprehensive multi-tenant gateway analytics for admin audits."""
    total_clients = db.query(Client).count()
    total_requests = db.query(UsageLog).count()
    total_credits = db.query(func.sum(UsageLog.credits_deducted)).scalar() or 0.0
    
    clients = db.query(Client).all()
    client_metrics = []
    
    for c in clients:
        calls_count = db.query(UsageLog).filter(UsageLog.client_id == c.id).count()
        credits_spent = db.query(func.sum(UsageLog.credits_deducted)).filter(UsageLog.client_id == c.id).scalar() or 0.0
        
        # Get the latest API key (active or revoked)
        key_record = db.query(ApiKey).filter(ApiKey.client_id == c.id).order_by(ApiKey.created_at.desc()).first()
        api_key_val = key_record.key if key_record else None
        api_key_active = key_record.is_active if key_record else False
        
        last_log = db.query(UsageLog).filter(UsageLog.client_id == c.id).order_by(UsageLog.timestamp.desc()).first()
        last_active = last_log.timestamp if last_log else None
        
        client_metrics.append(ClientMetrics(
            client_id=c.id,
            client_name=c.name,
            current_balance=c.wallet.balance if c.wallet else 0.0,
            total_calls=calls_count,
            total_credits_spent=credits_spent,
            api_key=api_key_val,
            api_key_active=api_key_active,
            last_active=last_active
        ))
        
    recent_db_logs = db.query(UsageLog).order_by(UsageLog.timestamp.desc()).limit(50).all()
    recent_logs = [
        UsageLogSummary(
            id=log.id,
            endpoint=log.endpoint,
            country=log.country,
            credits_deducted=log.credits_deducted,
            timestamp=log.timestamp,
            response_status=log.response_status
        )
        for log in recent_db_logs
    ]
    
    return AdminMetricsResponse(
        total_clients=total_clients,
        total_requests=total_requests,
        total_credits_deducted=total_credits,
        clients=client_metrics,
        recent_logs=recent_logs
    )

from fastapi.responses import HTMLResponse
from routers.dashboard import serve_dashboard

@router.get("/dashboard", response_class=HTMLResponse, summary="Serve Admin Dashboard UI")
async def serve_admin_dashboard():
    """Serves the dashboard HTML response for administrators."""
    return await serve_dashboard()
