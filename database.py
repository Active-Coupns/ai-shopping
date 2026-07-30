from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.orm import Session
from config import settings

# For SQLite, we specify check_same_thread=False
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

# Dependency to get db session in FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def seed_database(db: Session):
    """Seed the database with default affiliate configurations if they do not exist."""
    from models.affiliate import AffiliateConfig
    
    # Check if configs already exist
    if db.query(AffiliateConfig).count() > 0:
        return

    default_configs = [
        AffiliateConfig(
            country="US",
            store_name="Amazon",
            affiliate_tag="us-amazon-associate-20",
            coupon_code="USAMZ10",
            coupon_description="10% off selected electronics",
            is_active=True
        ),
        AffiliateConfig(
            country="US",
            store_name="Walmart",
            affiliate_tag="us-walmart-partner-20",
            coupon_code="WALMART5",
            coupon_description="Save $5 on orders over $50",
            is_active=True
        ),
        AffiliateConfig(
            country="IN",
            store_name="Amazon",
            affiliate_tag="in-amazon-associate-21",
            coupon_code="INAMZ100",
            coupon_description="Flat Rs 100 cashback on min buy Rs 1000",
            is_active=True
        ),
        AffiliateConfig(
            country="IN",
            store_name="Flipkart",
            affiliate_tag="in-flipkart-partner-21",
            coupon_code="FLIPKARTBANK",
            coupon_description="10% instant discount on SBI credit cards",
            is_active=True
        )
    ]
    
    db.add_all(default_configs)
    
    # Seed a default client for testing/dashboard access
    from models.client import Client
    from models.wallet import CreditWallet
    from models.api_key import ApiKey
    
    if db.query(Client).count() == 0:
        demo_client = Client(
            name="Acme Dev",
            email="acme@gateway.local",
            password="password123"
        )
        db.add(demo_client)
        db.flush()
        
        demo_wallet = CreditWallet(client_id=demo_client.id, balance=100.0, currency="USD")
        db.add(demo_wallet)
        
        demo_key = ApiKey(client_id=demo_client.id, key="gw_acmedemosecretkey123", is_active=True)
        db.add(demo_key)
        db.commit()

    # Ensure the requested key gw_49219b7938a801d920087bc153c6ec2b is seeded and active
    target_key = "gw_49219b7938a801d920087bc153c6ec2b"
    key_record = db.query(ApiKey).filter(ApiKey.key == target_key).first()
    if not key_record:
        # Resolve client to link this key to
        client_record = db.query(Client).filter(Client.email == "assistant@acme.com").first()
        if not client_record:
            client_record = db.query(Client).first()
        if not client_record:
            client_record = Client(
                name="Acme Dev",
                email="acme@gateway.local",
                password="password123"
            )
            db.add(client_record)
            db.flush()

        # Check/Create wallet
        wallet_record = db.query(CreditWallet).filter(CreditWallet.client_id == client_record.id).first()
        if not wallet_record:
            wallet_record = CreditWallet(client_id=client_record.id, balance=100.0, currency="USD")
            db.add(wallet_record)
        else:
            wallet_record.balance = 100.0

        # Add key
        new_key = ApiKey(client_id=client_record.id, key=target_key, is_active=True)
        db.add(new_key)
        db.commit()
    else:
        # Ensure it is active and has credits
        key_record.is_active = True
        wallet_record = db.query(CreditWallet).filter(CreditWallet.client_id == key_record.client_id).first()
        if wallet_record:
            wallet_record.balance = 100.0
        else:
            wallet_record = CreditWallet(client_id=key_record.client_id, balance=100.0, currency="USD")
            db.add(wallet_record)
        db.commit()
