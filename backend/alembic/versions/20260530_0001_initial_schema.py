"""Create the schema preceding the existing incremental migrations.

Revision ID: 20260530_0001
Revises:

This is a frozen snapshot of the original schema, including the cache columns
removed by 20260616_0002. Do not replace it with application model metadata.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260530_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_tokens", sa.BigInteger(), nullable=True),
        sa.Column("used_tokens", sa.BigInteger(), nullable=False),
        sa.Column("allowed_models", sa.Text(), nullable=True),
        sa.Column("rate_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_is_active", "api_keys", ["is_active"])

    op.create_table(
        "channels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("api_type", sa.String(16), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("timeout", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("upstream_models", sa.JSON(), nullable=False),
        sa.Column("custom_headers", sa.JSON(), nullable=True),
        sa.Column("health_status", sa.String(16), nullable=False),
        sa.Column("circuit_state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "model_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("api_type", sa.String(16), nullable=False),
        sa.Column("routing_strategy", sa.String(32), nullable=False),
        sa.Column("custom_js", sa.Text(), nullable=False),
        sa.Column("failover_enabled", sa.Boolean(), nullable=False),
        sa.Column("is_listed", sa.Boolean(), nullable=False),
        sa.Column("supports_thinking", sa.Boolean(), nullable=False),
        sa.Column("default_thinking_effort", sa.String(16), nullable=False),
        sa.Column("claude_thinking_mode", sa.String(16), nullable=False),
        sa.Column("enable_cache", sa.Boolean(), nullable=False),
        sa.Column("cache_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("cache_key_exclude_fields", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_model_configs_name", "model_configs", ["name"], unique=True)

    op.create_table(
        "model_channel_refs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("upstream_model_id", sa.String(256), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("inline_config", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["model_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
    )

    op.create_table(
        "plugins",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("hook_type", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("module_path", sa.String(512), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "request_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("api_key_hash", sa.String(128), nullable=False),
        sa.Column("api_type", sa.String(16), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("selected_channel_id", sa.String(36), nullable=True),
        sa.Column("selected_channel_name", sa.String(128), nullable=False),
        sa.Column("upstream_url", sa.String(1024), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("thinking_effort", sa.String(16), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_tokens", sa.Integer(), nullable=False),
        sa.Column("request_body", sa.Text(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("input_content", sa.Text(), nullable=False),
        sa.Column("output_content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_request_logs_trace_id", "request_logs", ["trace_id"])
    op.create_index("ix_request_logs_model", "request_logs", ["model"])


def downgrade() -> None:
    op.drop_table("request_logs")
    op.drop_table("plugins")
    op.drop_table("model_channel_refs")
    op.drop_table("model_configs")
    op.drop_table("channels")
    op.drop_table("api_keys")
