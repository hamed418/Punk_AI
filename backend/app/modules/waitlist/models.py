import uuid 
from app.db.models import Base
from sqlalchemy import (
    Column, String, Text, DateTime, ForeignKey,
    Numeric, JSON, Boolean, Integer, Enum as SAEnum, Float,   Identity
)
from sqlalchemy.dialects.postgresql import UUID,TIMESTAMP
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
import enum



class WaitList(Base):
    __tablename__ = "wait_list"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # user info  
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)
    linkedin_url = Column(String(255), nullable=True)
    job_title = Column(String(255), nullable=True) 
    description = Column(Text, nullable=True) 

    # Network & Geolocation
    ip_address = Column(String(45), nullable=True)         # IPv4 / IPv6
    country = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    timezone = Column(String(100), nullable=True)
    isp = Column(String(255), nullable=True)

    # Device Information
    user_agent = Column(Text, nullable=True)
    browser = Column(String(100), nullable=True)
    browser_version = Column(String(50), nullable=True)
    operating_system = Column(String(100), nullable=True)
    os_version = Column(String(50), nullable=True)
    device_type = Column(String(50), nullable=True)   # desktop/mobile/tablet
    device_brand = Column(String(100), nullable=True)
    device_model = Column(String(100), nullable=True)

    # Marketing Attribution
    referrer_url = Column(Text, nullable=True)
    landing_page = Column(Text, nullable=True)

    utm_source = Column(String(255), nullable=True)
    utm_medium = Column(String(255), nullable=True)
    utm_campaign = Column(String(255), nullable=True)
    utm_term = Column(String(255), nullable=True)
    utm_content = Column(String(255), nullable=True)

    # Language
    language = Column(String(20), nullable=True)

    # Status
    is_completed = Column(Boolean, nullable=False, server_default="false")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())