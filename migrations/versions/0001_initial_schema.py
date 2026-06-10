"""Initial TLS schema

Revision ID: 0001
Revises:
Create Date: 2026-06-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── tls_tiers ──────────────────────────────────────────────────────────────
    op.create_table(
        "tls_tiers",
        sa.Column("tier_id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("limits", postgresql.JSONB, nullable=False),
        sa.Column("cost_multiplier", sa.Numeric(4, 2), nullable=False, server_default="1.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )

    # ── tls_users ──────────────────────────────────────────────────────────────
    op.create_table(
        "tls_users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tier_id", sa.String(50), sa.ForeignKey("tls_tiers.tier_id"), nullable=False, server_default="free"),
        sa.Column("custom_limits", postgresql.JSONB, nullable=True),
        sa.Column("hard_balance", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tls_users_org_id", "tls_users", ["org_id"])

    # ── tls_usage (partitioned by period_start, monthly) ──────────────────────
    op.execute("""
        CREATE TABLE tls_usage (
            id           BIGSERIAL,
            user_id      UUID        NOT NULL,
            org_id       UUID,
            request_id   UUID        NOT NULL,
            period_type  VARCHAR(20) NOT NULL,
            period_start TIMESTAMPTZ NOT NULL,
            tokens_input  BIGINT NOT NULL DEFAULT 0,
            tokens_output BIGINT NOT NULL DEFAULT 0,
            tokens_total  BIGINT NOT NULL,
            model_id     VARCHAR(50),
            metadata     JSONB,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, period_start)
        ) PARTITION BY RANGE (period_start)
    """)

    # Partitioned tables require the partition key in every unique constraint.
    # (request_id, period_start) satisfies PostgreSQL; the Redis finalized-key
    # is the primary double-billing guard and this is the DB-level backstop.
    op.execute("CREATE UNIQUE INDEX ix_tls_usage_request_id ON tls_usage (request_id, period_start)")
    op.execute("CREATE INDEX ix_tls_usage_user_period ON tls_usage (user_id, period_start)")

    # Create first two monthly partitions
    op.execute("""
        CREATE TABLE tls_usage_2026_06
            PARTITION OF tls_usage
            FOR VALUES FROM ('2026-06-01') TO ('2026-07-01')
    """)
    op.execute("""
        CREATE TABLE tls_usage_2026_07
            PARTITION OF tls_usage
            FOR VALUES FROM ('2026-07-01') TO ('2026-08-01')
    """)

    # ── tls_limit_changes (audit log) ─────────────────────────────────────────
    op.create_table(
        "tls_limit_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_by", sa.String(100), nullable=True),
        sa.Column("old_limits", postgresql.JSONB, nullable=True),
        sa.Column("new_limits", postgresql.JSONB, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── Seed default tiers via bulk_insert (avoids JSON colon/bind-param clash) ──
    tiers_table = sa.table(
        "tls_tiers",
        sa.column("tier_id", sa.String),
        sa.column("name", sa.String),
        sa.column("limits", postgresql.JSONB),
        sa.column("cost_multiplier", sa.Numeric),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(tiers_table, [
        {
            "tier_id": "free", "name": "Free", "is_active": True, "cost_multiplier": 1.0,
            "limits": {"daily_tokens": 10000, "monthly_tokens": 100000, "rpm": 10, "rph": 100, "tpm": 20000, "concurrent_requests": 3},
        },
        {
            "tier_id": "pro", "name": "Pro", "is_active": True, "cost_multiplier": 1.0,
            "limits": {"daily_tokens": 100000, "monthly_tokens": 2000000, "rpm": 60, "rph": 1000, "tpm": 200000, "concurrent_requests": 10},
        },
        {
            "tier_id": "enterprise", "name": "Enterprise", "is_active": True, "cost_multiplier": 1.0,
            "limits": {"daily_tokens": 1000000, "monthly_tokens": 20000000, "rpm": 200, "rph": 5000, "tpm": 1000000, "concurrent_requests": 50},
        },
    ])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tls_usage_2026_07")
    op.execute("DROP TABLE IF EXISTS tls_usage_2026_06")
    op.execute("DROP TABLE IF EXISTS tls_usage CASCADE")
    op.drop_table("tls_limit_changes")
    op.drop_table("tls_users")
    op.drop_table("tls_tiers")
