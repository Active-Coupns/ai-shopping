from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class AffiliateConfig(Base):
    __tablename__ = "affiliate_configs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True) # Null = global config default
    country = Column(String, index=True, nullable=False) # e.g. "US" or "IN"
    store_name = Column(String, index=True, nullable=False) # e.g. "Amazon", "Walmart", "Flipkart"
    affiliate_tag = Column(String, nullable=False) # e.g. associate ID
    coupon_code = Column(String, nullable=True) # e.g. "SAVE10"
    coupon_description = Column(String, nullable=True) # e.g. "10% off items"
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Smart Hybrid Monitisation settings
    aggregator_network_name = Column(String, nullable=True) # e.g. "CueLinks", "Skimlinks"
    aggregator_publisher_id = Column(String, nullable=True)
    aggregator_url_template = Column(String, nullable=True) # e.g. https://links2re.com/?pub_id={PUB_ID}&url={URL}
    amazon_tag_in = Column(String, nullable=True)
    amazon_tag_us = Column(String, nullable=True)
    flipkart_subid = Column(String, nullable=True)

    # Relationships
    client = relationship("Client", back_populates="affiliate_configs")
