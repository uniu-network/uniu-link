"""add from apikey fields to request logs

Revision ID: 20260621_0001
Revises: 20260616_0002
Create Date: 2026-06-21 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260621_0001"
down_revision: Union[str, None] = "20260616_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "request_logs",
        sa.Column("from_apikey", sa.String(length=36), nullable=False, server_default=""),
    )
    op.add_column(
        "request_logs",
        sa.Column("from_apikey_name", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_index("ix_request_logs_from_apikey", "request_logs", ["from_apikey"])


def downgrade() -> None:
    op.drop_index("ix_request_logs_from_apikey", table_name="request_logs")
    op.drop_column("request_logs", "from_apikey_name")
    op.drop_column("request_logs", "from_apikey")
