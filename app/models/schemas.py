from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── /limits/check ─────────────────────────────────────────────────────────────

class CheckRequest(BaseModel):
    user_id: str
    estimated_tokens: int = Field(default=0, ge=0)


class CheckResponse(BaseModel):
    allowed: bool
    tokens_used: int
    token_limit: int
    unblocked_at: Optional[datetime] = None
    reason: Optional[str] = None


# ── /limits/consume ───────────────────────────────────────────────────────────

class ConsumeRequest(BaseModel):
    user_id: str
    tokens: int = Field(ge=0)


class ConsumeResponse(BaseModel):
    consumed: bool
    tokens_used: int
    token_limit: int
    blocked: bool
    unblocked_at: Optional[datetime] = None


# ── /limits/status ────────────────────────────────────────────────────────────

class StatusResponse(BaseModel):
    user_id: str
    tokens_used: int
    token_limit: int
    blocked: bool
    blocked_at: Optional[datetime] = None
    unblocked_at: Optional[datetime] = None


# ── /admin/reset ──────────────────────────────────────────────────────────────

class AdminResetRequest(BaseModel):
    user_id: str
    reset_by: str = "admin"


class AdminResetResponse(BaseModel):
    reset: bool
    user_id: str


# ── Health ────────────────────────────────────────────────────────────────────

class HealthLiveResponse(BaseModel):
    status: str = "ok"


class HealthReadyResponse(BaseModel):
    status: str
    mongodb: str
