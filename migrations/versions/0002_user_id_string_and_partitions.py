"""Change user_id from UUID to VARCHAR and add monthly partitions through 2027-12

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-15

Why: Keural FastAPI passes user_id as a plain string (e.g. "user_12345"), not a
UUID. This migration aligns the TLS schema with the actual upstream value so the
service no longer rejects valid check/consume requests with a 422 error.

Partition note: the partitioned tls_usage table needs a child partition for every
calendar month that will receive writes. INSERT fails if no matching partition
exists. We add 2026-08 through 2027-12 here; a cron-based auto-partition job
should be added before production to keep this running indefinitely.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Change user_id columns from UUID → VARCHAR(255) ────────────────────────
    #
    # tls_users.user_id is the primary key — no FK references it from other
    # tables so we can safely retype it with USING user_id::text.
    op.execute("""
        ALTER TABLE tls_users
        ALTER COLUMN user_id TYPE VARCHAR(255) USING user_id::text
    """)

    # tls_usage is PARTITIONED. In PostgreSQL 14+ altering the parent table
    # propagates the type change to all existing child partitions automatically.
    op.execute("""
        ALTER TABLE tls_usage
        ALTER COLUMN user_id TYPE VARCHAR(255) USING user_id::text
    """)

    op.execute("""
        ALTER TABLE tls_limit_changes
        ALTER COLUMN user_id TYPE VARCHAR(255) USING user_id::text
    """)

    # ── Add monthly partitions 2026-08 → 2027-12 ─────────────────────────────
    months = [
        # 2026
        ("2026_08", "2026-08-01", "2026-09-01"),
        ("2026_09", "2026-09-01", "2026-10-01"),
        ("2026_10", "2026-10-01", "2026-11-01"),
        ("2026_11", "2026-11-01", "2026-12-01"),
        ("2026_12", "2026-12-01", "2027-01-01"),
        # 2027
        ("2027_01", "2027-01-01", "2027-02-01"),
        ("2027_02", "2027-02-01", "2027-03-01"),
        ("2027_03", "2027-03-01", "2027-04-01"),
        ("2027_04", "2027-04-01", "2027-05-01"),
        ("2027_05", "2027-05-01", "2027-06-01"),
        ("2027_06", "2027-06-01", "2027-07-01"),
        ("2027_07", "2027-07-01", "2027-08-01"),
        ("2027_08", "2027-08-01", "2027-09-01"),
        ("2027_09", "2027-09-01", "2027-10-01"),
        ("2027_10", "2027-10-01", "2027-11-01"),
        ("2027_11", "2027-11-01", "2027-12-01"),
        ("2027_12", "2027-12-01", "2028-01-01"),
    ]

    for suffix, start, end in months:
        op.execute(f"""
            CREATE TABLE tls_usage_{suffix}
                PARTITION OF tls_usage
                FOR VALUES FROM ('{start}') TO ('{end}')
        """)


def downgrade() -> None:
    # Drop partitions added in this migration
    months = [
        "2026_08", "2026_09", "2026_10", "2026_11", "2026_12",
        "2027_01", "2027_02", "2027_03", "2027_04", "2027_05",
        "2027_06", "2027_07", "2027_08", "2027_09", "2027_10",
        "2027_11", "2027_12",
    ]
    for suffix in months:
        op.execute(f"DROP TABLE IF EXISTS tls_usage_{suffix}")

    # Revert user_id columns back to UUID
    op.execute("""
        ALTER TABLE tls_limit_changes
        ALTER COLUMN user_id TYPE UUID USING user_id::uuid
    """)
    op.execute("""
        ALTER TABLE tls_usage
        ALTER COLUMN user_id TYPE UUID USING user_id::uuid
    """)
    op.execute("""
        ALTER TABLE tls_users
        ALTER COLUMN user_id TYPE UUID USING user_id::uuid
    """)
