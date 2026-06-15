from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TLSTier(Base):
    __tablename__ = "tls_tiers"

    tier_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False)
    cost_multiplier: Mapped[float] = mapped_column(Numeric(4, 2), default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TLSUser(Base):
    __tablename__ = "tls_users"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    tier_id: Mapped[str] = mapped_column(String(50), ForeignKey("tls_tiers.tier_id"), default="free")
    custom_limits: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    hard_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))


class TLSUsage(Base):
    """One record per LLM request. Partitioned by period_start (monthly)."""

    __tablename__ = "tls_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    request_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, primary_key=True)
    tokens_input: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_output: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    model_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))


class TLSLimitChange(Base):
    __tablename__ = "tls_limit_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    changed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    old_limits: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_limits: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
