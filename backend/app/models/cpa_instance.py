import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class CpaInstance(Base):
    """由 UniuLink 托管的 CLIProxyAPI 运行实例。

    pid 与 status 只是持久化快照，真实存活状态以进程探测与 /healthz 为准，
    不使用 ORM 字段直接判断运行时状态。
    """

    __tablename__ = "cpa_instances"

    # updated_at 使用 SQL 表达式 onupdate=func.now()，ORMs 无法预知数据库生成的值，
    # 默认会在每次 UPDATE 后把该属性标记为过期；异步会话中再读取它就会触发同步
    # 延迟加载，抛 MissingGreenlet（表现为管理接口 500）。开启 eager_defaults 后
    # UPDATE 会带 RETURNING 把新值随同一条语句取回，属性不再过期。
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    host: Mapped[str] = mapped_column(String(64), nullable=False, default="127.0.0.1")
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    binary_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    managed_binary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    install_dir: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    config_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    auth_dir: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    log_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    encrypted_management_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    encrypted_access_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    auto_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="stopped")
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
