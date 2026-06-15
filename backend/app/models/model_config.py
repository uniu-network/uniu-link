import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    api_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="openai"
    )
    routing_strategy: Mapped[str] = mapped_column(
        String(32), default="default"
    )
    custom_js: Mapped[str] = mapped_column(Text, default="")
    failover_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_listed: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    default_thinking_effort: Mapped[str] = mapped_column(String(16), default="none")
    claude_thinking_mode: Mapped[str] = mapped_column(String(16), default="adaptive")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
