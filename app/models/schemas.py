from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── /limits/check ─────────────────────────────────────────────────────────────

class CheckRequest(BaseModel):
    user_id: uuid.UUID
    org_id: Optional[uuid.UUID] = None
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    model_id: str = "gpt-4o"
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class CheckAllowedResponse(BaseModel):
    allowed: bool = True
    request_id: uuid.UUID
    remaining_tokens: int
    resets_at: str
    tier: str


class CheckBlockedResponse(BaseModel):
    allowed: bool = False
    reason: str
    limit_type: str
    current_usage: Optional[int] = None
    limit: Optional[int] = None
    resets_at: str
    suggested_action: str


# ── /limits/consume ───────────────────────────────────────────────────────────

class ConsumeRequest(BaseModel):
    user_id: uuid.UUID
    request_id: uuid.UUID
    actual_input_tokens: int = Field(ge=0)
    actual_output_tokens: int = Field(ge=0)
    model_id: str = "gpt-4o"
    metadata: Optional[dict[str, Any]] = None


class ConsumeResponse(BaseModel):
    consumed: bool
    total_deducted: int
    new_balance: int
    overage: int
    refunded: int


# ── /limits/usage ─────────────────────────────────────────────────────────────

class UsageResponse(BaseModel):
    user_id: uuid.UUID
    tier: str
    daily_used: int
    daily_limit: Optional[int]
    monthly_used: int
    monthly_limit: Optional[int]
    resets_at: str
    period_date: str


# ── /limits/history ───────────────────────────────────────────────────────────

class HistoryRecord(BaseModel):
    request_id: uuid.UUID
    tokens_input: int
    tokens_output: int
    tokens_total: int
    model_id: Optional[str]
    created_at: str
    metadata: Optional[dict[str, Any]]


class HistoryResponse(BaseModel):
    user_id: uuid.UUID
    page: int
    page_size: int
    total: int
    records: list[HistoryRecord]


# ── /admin/limits ─────────────────────────────────────────────────────────────

class AdminSetLimitsRequest(BaseModel):
    user_id: Optional[uuid.UUID] = None
    org_id: Optional[uuid.UUID] = None
    limits: dict[str, Any]
    reason: Optional[str] = None
    changed_by: str


class AdminSetLimitsResponse(BaseModel):
    updated: bool
    user_id: Optional[uuid.UUID]
    org_id: Optional[uuid.UUID]
    new_limits: dict[str, Any]


# ── /admin/refill ─────────────────────────────────────────────────────────────

class AdminRefillRequest(BaseModel):
    user_id: uuid.UUID
    tokens: int = Field(gt=0)
    reason: Optional[str] = None
    changed_by: str


class AdminRefillResponse(BaseModel):
    refilled: bool
    user_id: uuid.UUID
    tokens_added: int
    new_balance: int


# ── /admin/tiers ──────────────────────────────────────────────────────────────

class TierCreate(BaseModel):
    tier_id: str = Field(max_length=50)
    name: str = Field(max_length=100)
    limits: dict[str, Any]
    cost_multiplier: float = Field(default=1.0, ge=0)
    is_active: bool = True


class TierResponse(BaseModel):
    tier_id: str
    name: str
    limits: dict[str, Any]
    cost_multiplier: float
    is_active: bool


# ── Health ────────────────────────────────────────────────────────────────────

class HealthLiveResponse(BaseModel):
    status: str = "ok"


class HealthReadyResponse(BaseModel):
    status: str
    postgres: str
    redis: str
