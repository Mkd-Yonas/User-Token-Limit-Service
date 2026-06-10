"""Core check flow — implements spec section 6.1."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.schemas import CheckRequest
from app.services.quota_service import get_daily_usage, get_monthly_usage, get_user_limits
from app.services.rate_limiter import RateLimiter
from app.utils.idempotency import is_request_finalized, is_request_pending
from app.utils.token_estimator import calculate_cost

logger = logging.getLogger(__name__)


def _reset_eod() -> str:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.isoformat()


def _reset_eom() -> str:
    now = datetime.now(timezone.utc)
    mo = now.month
    yr = now.year
    if mo == 12:
        yr, mo = yr + 1, 1
    else:
        mo += 1
    return datetime(yr, mo, 1, tzinfo=timezone.utc).isoformat()


def _reset_in(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


async def _get_reserved(user_id: str, date: str, redis: Redis) -> int:
    val = await redis.get(f"tls:pending_tokens:{user_id}:{date}")
    return int(val) if val else 0


async def _reserve(
    user_id: str,
    request_id: str,
    date: str,
    tokens: int,
    tier: str,
    remaining: int,
    redis: Redis,
) -> None:
    pending_key = f"tls:pending_tokens:{user_id}:{date}"
    request_key = f"tls:pending:{request_id}"
    now = time.time()

    async with redis.pipeline(transaction=True) as pipe:
        pipe.incrby(pending_key, tokens)
        pipe.expire(pending_key, 86_400)
        pipe.hset(
            request_key,
            mapping={
                "user_id": user_id,
                "tokens": tokens,
                "date": date,
                "tier": tier,
                "remaining": remaining,
            },
        )
        pipe.expire(request_key, settings.reaper_stale_threshold_minutes * 60 * 2)
        pipe.zadd("tls:pending_set", {request_id: now})
        await pipe.execute()


async def check_limits(
    req: CheckRequest,
    db: AsyncSession,
    redis: Redis,
) -> tuple[bool, dict[str, Any]]:
    """Returns (allowed, response_payload)."""

    user_id = str(req.user_id)
    request_id = str(req.request_id)
    now_utc = datetime.now(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    month = now_utc.strftime("%Y-%m")

    # Idempotency: if already pending return cached state
    if await is_request_pending(request_id, redis):
        data = await redis.hgetall(f"tls:pending:{request_id}")
        if data:
            return True, {
                "allowed": True,
                "request_id": request_id,
                "remaining_tokens": int(data.get(b"remaining", 0)),
                "resets_at": _reset_eod(),
                "tier": (data.get(b"tier") or b"free").decode(),
            }

    # Idempotency: if already finalized, block duplicate
    if await is_request_finalized(request_id, redis):
        return False, {
            "allowed": False,
            "reason": "REQUEST_ALREADY_CONSUMED",
            "limit_type": "idempotency",
            "resets_at": _reset_in(0),
            "suggested_action": "USE_NEW_REQUEST_ID",
        }

    limits = await get_user_limits(user_id, db, redis)
    tier = limits.get("tier_id", settings.default_tier)
    estimated_total = int(calculate_cost(req.estimated_input_tokens, req.estimated_output_tokens, req.model_id))

    rate = RateLimiter(redis)

    # ── Rate limits (fast reject) ──────────────────────────────────────────────

    if "rpm" in limits and limits["rpm"]:
        if not await rate.check_rpm(user_id, limits["rpm"]):
            return False, {
                "allowed": False,
                "reason": "RATE_LIMIT_EXCEEDED",
                "limit_type": "requests_per_minute",
                "resets_at": _reset_in(60),
                "suggested_action": "WAIT",
            }

    if "rph" in limits and limits["rph"]:
        if not await rate.check_rph(user_id, limits["rph"]):
            return False, {
                "allowed": False,
                "reason": "RATE_LIMIT_EXCEEDED",
                "limit_type": "requests_per_hour",
                "resets_at": _reset_in(3600),
                "suggested_action": "WAIT",
            }

    if settings.enable_model_multipliers and "tpm" in limits and limits["tpm"]:
        if not await rate.check_tpm(user_id, estimated_total, limits["tpm"]):
            return False, {
                "allowed": False,
                "reason": "RATE_LIMIT_EXCEEDED",
                "limit_type": "tokens_per_minute",
                "resets_at": _reset_in(60),
                "suggested_action": "WAIT",
            }

    if settings.enable_concurrent_limits and "concurrent_requests" in limits and limits["concurrent_requests"]:
        concurrent = await rate.get_concurrent(user_id)
        if concurrent >= limits["concurrent_requests"]:
            return False, {
                "allowed": False,
                "reason": "CONCURRENT_LIMIT_EXCEEDED",
                "limit_type": "concurrent_requests",
                "current_usage": concurrent,
                "limit": limits["concurrent_requests"],
                "resets_at": _reset_in(30),
                "suggested_action": "WAIT",
            }

    # ── Quota checks ───────────────────────────────────────────────────────────

    daily_limit: int | None = limits.get("daily_tokens")
    if daily_limit:
        daily_used = await get_daily_usage(user_id, today, db, redis)
        reserved = await _get_reserved(user_id, today, redis)
        if daily_used + reserved + estimated_total > daily_limit:
            return False, {
                "allowed": False,
                "reason": "TOKEN_QUOTA_EXCEEDED",
                "limit_type": "daily_tokens",
                "current_usage": daily_used,
                "limit": daily_limit,
                "resets_at": _reset_eod(),
                "suggested_action": "UPGRADE_TIER" if tier == "free" else "WAIT",
            }

    monthly_limit: int | None = limits.get("monthly_tokens")
    if monthly_limit:
        monthly_used = await get_monthly_usage(user_id, month, db, redis)
        if monthly_used + estimated_total > monthly_limit:
            return False, {
                "allowed": False,
                "reason": "TOKEN_QUOTA_EXCEEDED",
                "limit_type": "monthly_tokens",
                "current_usage": monthly_used,
                "limit": monthly_limit,
                "resets_at": _reset_eom(),
                "suggested_action": "UPGRADE_TIER",
            }

    # ── Reserve tokens ─────────────────────────────────────────────────────────

    daily_used = await get_daily_usage(user_id, today, db, redis)
    remaining = max(0, (daily_limit or 0) - daily_used - estimated_total)

    await rate.increment_concurrent(user_id)
    await _reserve(user_id, request_id, today, estimated_total, tier, remaining, redis)

    return True, {
        "allowed": True,
        "request_id": request_id,
        "remaining_tokens": remaining,
        "resets_at": _reset_eod(),
        "tier": tier,
    }
