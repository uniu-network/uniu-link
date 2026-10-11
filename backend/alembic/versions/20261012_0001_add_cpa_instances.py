"""add managed CLIProxyAPI instances and channel binding

Revision ID: 20261012_0001
Revises: 20261005_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20261012_0001"
down_revision = "20261005_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cpa_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("host", sa.String(length=64), nullable=False, server_default="127.0.0.1"),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("binary_path", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("managed_binary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("install_dir", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("config_path", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("auth_dir", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("log_path", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("encrypted_management_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("encrypted_access_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("auto_start", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="stopped"),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # SQLite cannot ALTER TABLE ADD CONSTRAINT, so the channel binding uses
    # batch mode to stay valid on both SQLite and PostgreSQL.
    with op.batch_alter_table("channels") as batch_op:
        batch_op.add_column(sa.Column("cpa_instance_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("auto_managed", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_foreign_key(
            "fk_channels_cpa_instance_id",
            "cpa_instances",
            ["cpa_instance_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch_op:
        batch_op.drop_constraint("fk_channels_cpa_instance_id", type_="foreignkey")
        batch_op.drop_column("auto_managed")
        batch_op.drop_column("cpa_instance_id")
    op.drop_table("cpa_instances")
