"""Add a persistent presentation-only model icon preference.

Revision ID: 20261005_0001
Revises: 20260621_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20261005_0001"
down_revision = "20260621_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("icon", sa.String(length=32), nullable=False, server_default="auto"),
    )


def downgrade() -> None:
    op.drop_column("model_configs", "icon")
