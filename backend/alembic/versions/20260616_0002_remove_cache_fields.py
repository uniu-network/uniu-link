"""remove cache fields

Revision ID: 20260616_0002
Revises: 20260616_0001
Create Date: 2026-06-16 00:55:54.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260616_0002"
down_revision: Union[str, None] = "20260616_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("model_configs", "enable_cache")
    op.drop_column("model_configs", "cache_ttl_seconds")
    op.drop_column("model_configs", "cache_key_exclude_fields")
    op.drop_column("request_logs", "cache_hit")


def downgrade() -> None:
    op.add_column(
        "request_logs",
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "model_configs",
        sa.Column("cache_key_exclude_fields", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "model_configs",
        sa.Column("cache_ttl_seconds", sa.Integer(), nullable=False, server_default="3600"),
    )
    op.add_column(
        "model_configs",
        sa.Column("enable_cache", sa.Boolean(), nullable=False, server_default="false"),
    )
