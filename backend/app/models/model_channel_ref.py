import uuid
from sqlalchemy import String, Integer, Float, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ModelChannelRef(Base):
    __tablename__ = "model_channel_refs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_configs.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    upstream_model_id: Mapped[str] = mapped_column(String(256), default="")
    type: Mapped[str] = mapped_column(String(16), default="reference")
    inline_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
