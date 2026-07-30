from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    password = Column(String, nullable=True) # Direct password for gateway demo purposes
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # White-Label & Affiliate settings
    primary_strategy = Column(String, default="direct", nullable=False) # "cuelinks" or "direct"
    cuelinks_pub_id = Column(String, nullable=True)
    amazon_tag = Column(String, nullable=True)
    flipkart_tag = Column(String, nullable=True)
    amazon_tag_in = Column(String, nullable=True)
    amazon_tag_us = Column(String, nullable=True)

    # Relationships
    api_keys = relationship("ApiKey", back_populates="client", cascade="all, delete-orphan")
    wallet = relationship("CreditWallet", back_populates="client", uselist=False, cascade="all, delete-orphan")
    usage_logs = relationship("UsageLog", back_populates="client", cascade="all, delete-orphan")
    affiliate_configs = relationship("AffiliateConfig", back_populates="client", cascade="all, delete-orphan")
