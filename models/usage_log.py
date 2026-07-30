from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    endpoint = Column(String, nullable=False)
    country = Column(String, nullable=True)
    credits_deducted = Column(Float, default=0.0, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    request_payload = Column(Text, nullable=True)
    response_status = Column(Integer, nullable=False)

    # Relationships
    client = relationship("Client", back_populates="usage_logs")
