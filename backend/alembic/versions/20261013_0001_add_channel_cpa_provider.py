"""add cpa_provider to channels for per-account-type managed channels

Revision ID: 20261013_0001
Revises: 20261012_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20261013_0001"
down_revision = "20261012_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 托管渠道改为按账号类型拆分，需要记录渠道对应的账号类型。
    # 历史行保持 NULL，同步流程会把它们重建为按类型拆分的渠道。
    with op.batch_alter_table("channels") as batch_op:
        batch_op.add_column(sa.Column("cpa_provider", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch_op:
        batch_op.drop_column("cpa_provider")
