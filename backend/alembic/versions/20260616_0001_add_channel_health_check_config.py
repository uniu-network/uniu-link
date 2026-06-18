"""add channel health check config

Revision ID: 20260616_0001
Revises:
Create Date: 2026-06-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260616_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_HEALTH_CHECK_PROMPT = "Hi, please respond with a short greeting to confirm you are working."


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("health_check_mode", sa.String(length=16), nullable=False, server_default="model_list"),
    )
    op.add_column(
        "channels",
        sa.Column("health_check_model", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "channels",
        sa.Column("health_check_prompt", sa.Text(), nullable=False, server_default=DEFAULT_HEALTH_CHECK_PROMPT),
    )
    op.add_column(
        "channels",
        sa.Column("health_check_max_tokens", sa.Integer(), nullable=False, server_default="32"),
    )


def downgrade() -> None:
    op.drop_column("channels", "health_check_max_tokens")
    op.drop_column("channels", "health_check_prompt")
    op.drop_column("channels", "health_check_model")
    op.drop_column("channels", "health_check_mode")
