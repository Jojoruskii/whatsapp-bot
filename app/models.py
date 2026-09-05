from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from app.database import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    quantity = Column(Integer, default=0)
    reorder_level = Column(Integer, default=5)
    category = Column(String, nullable=True, default="Uncategorized")


class ConversationState(Base):
    """Tracks the last product each WhatsApp sender mentioned, so follow-up
    messages like "add 5 more" can resolve which product they mean without
    needing to resend a full chat transcript to Claude on every message."""
    __tablename__ = "conversation_state"

    phone = Column(String, primary_key=True, index=True)
    last_product = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
