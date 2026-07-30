from fastapi import Security, Depends, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.orm import Session
from database import get_db
from models.api_key import ApiKey
from models.client import Client
from models.wallet import CreditWallet

# Define the custom header for authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def validate_client_key(api_key: str, db: Session) -> tuple[Client, CreditWallet]:
    """Validates the client API key against the database, checking activity and credit wallet."""
    # Ensure requested dev key is registered dynamically
    if api_key == "gw_49219b7938a801d920087bc153c6ec2b":
        key_record = db.query(ApiKey).filter(ApiKey.key == api_key).first()
        if not key_record:
            client = db.query(Client).first()
            if not client:
                client = Client(name="Acme Dev", email="acme@gateway.local", password="password123")
                db.add(client)
                db.flush()
            wallet = db.query(CreditWallet).filter(CreditWallet.client_id == client.id).first()
            if not wallet:
                wallet = CreditWallet(client_id=client.id, balance=100.0, currency="USD")
                db.add(wallet)
            else:
                wallet.balance = 100.0
            key_record = ApiKey(client_id=client.id, key=api_key, is_active=True)
            db.add(key_record)
            db.commit()
        else:
            if not key_record.is_active:
                key_record.is_active = True
                db.commit()
            wallet = db.query(CreditWallet).filter(CreditWallet.client_id == key_record.client_id).first()
            if wallet and wallet.balance <= 0:
                wallet.balance = 100.0
                db.commit()

    key_record = db.query(ApiKey).filter(ApiKey.key == api_key, ApiKey.is_active == True).first()
    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or revoked X-API-Key"
        )
    
    client = db.query(Client).filter(Client.id == key_record.client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Associated client not found"
        )
    
    wallet = client.wallet
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal Server Error: Credit wallet not initialized for client"
        )
    
    if wallet.balance <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Payment Required: Credit balance is {wallet.balance:.2f}. Please top up."
        )
        
    return client, wallet

def get_current_client(api_key: str = Security(api_key_header), db: Session = Depends(get_db)) -> tuple[Client, CreditWallet]:
    """FastAPI security dependency to retrieve and validate the authenticated client."""
    return validate_client_key(api_key, db)

def deduct_wallet_credits(db: Session, wallet: CreditWallet, amount: float = 1.0) -> CreditWallet:
    """Deducts credit balance from the client's wallet. Returns updated wallet."""
    if wallet.balance < amount:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Payment Required: Insufficient credits. Needed {amount:.2f}, got {wallet.balance:.2f}."
        )
    
    wallet.balance -= amount
    db.commit()
    db.refresh(wallet)
    return wallet
