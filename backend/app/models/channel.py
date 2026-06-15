import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="openai"
    )
    api_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="openai"
    )
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    timeout: Mapped[int] = mapped_column(Integer, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    upstream_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    custom_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    health_status: Mapped[str] = mapped_column(String(16), default="unknown")
    circuit_state: Mapped[str] = mapped_column(String(16), default="closed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
