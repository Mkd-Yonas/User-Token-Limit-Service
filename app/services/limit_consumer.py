"""Core consume flow — implements spec section 6.2."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import TLSUsage
from app.models.schemas import ConsumeRequest
from app.services.quota_service import get_daily_usage, get_user_limits
from app.services.rate_limiter import RateLimiter
from app.utils.idempotency import is_request_finalized, mark_request_finalized
from app.utils.token_estimator import calculate_cost

logger = logging.getLogger(__name__)

GRACE = settings.grace_percentage / 100


async def consume_tokens(
    req: ConsumeRequest,
    db: AsyncSession,
    redis: Redis,
) -> dict[str, Any]:
    user_id = str(req.user_id)
    request_id = str(req.request_id)
    now_utc = datetime.now(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    month = now_utc.strftime("%Y-%m")

    # Idempotency guard
    if await is_request_finalized(request_id, redis):
        logger.warning("Duplicate consume ignored: %s", request_id)
        return {"consumed": True, "total_deducted": 0, "new_balance": 0, "overage": 0, "refunded": 0}

    # Retrieve reservation
    pending_key = f"tls:pending:{request_id}"
    raw = await redis.hgetall(pending_key)
    reserved = int(raw.get(b"tokens", 0)) if raw else 0

    # Calculate actual cost
    actual_cost = int(calculate_cost(req.actual_input_tokens, req.actual_output_tokens, req.model_id))

    refund = max(0, reserved - actual_cost)
    overage = max(0, actual_cost - reserved)

    # ── Overage handling (spec 6.3) ────────────────────────────────────────────
    if overage > 0 and reserved > 0:
        overage_ratio = overage / reserved
        if overage_ratio <= GRACE:
            # Allow; deduct exact
            pass
        elif settings.strict_mode:
            logger.warning("Overage %.1f%% exceeds grace for request %s", overage_ratio * 100, request_id)

    # ── Write PostgreSQL record ────────────────────────────────────────────────
    day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    usage = TLSUsage(
        user_id=req.user_id,
        request_id=req.request_id,
        period_type="daily",
        period_start=day_start,
        tokens_input=req.actual_input_tokens,
        tokens_output=req.actual_output_tokens,
        tokens_total=actual_cost,
        model_id=req.model_id,
        metadata_=req.metadata,
        created_at=now_utc,
    )
    db.add(usage)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to persist usage record for request %s", request_id)
        raise

    # ── Update Redis state ─────────────────────────────────────────────────────
    pending_tokens_key = f"tls:pending_tokens:{user_id}:{today}"
    daily_cache_key = f"tls:cache:daily:{user_id}:{today}"
    monthly_cache_key = f"tls:cache:monthly:{user_id}:{month}"

    async with redis.pipeline(transaction=True) as pipe:
        pipe.decrby(pending_tokens_key, reserved)
        pipe.incrby(daily_cache_key, actual_cost)
        pipe.incrby(monthly_cache_key, actual_cost)
        pipe.setex(f"tls:finalized:{request_id}", 86_400, "1")
        pipe.zrem("tls:pending_set", request_id)
        pipe.delete(pending_key)
        await pipe.execute()

    # Decrement concurrent counter
    await RateLimiter(redis).decrement_concurrent(user_id)

    # Compute new balance
    limits = await get_user_limits(user_id, db, redis)
    daily_limit: int = limits.get("daily_tokens", 0)
    await redis.delete(daily_cache_key)  # invalidate so next read is fresh
    daily_used = await get_daily_usage(user_id, today, db, redis)
    new_balance = max(0, daily_limit - daily_used)

    return {
        "consumed": True,
        "total_deducted": actual_cost,
        "new_balance": new_balance,
        "overage": overage,
        "refunded": refund,
    }
