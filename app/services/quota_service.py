"""Daily / monthly quota calculations backed by Redis cache + PostgreSQL."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import TLSTier, TLSUsage, TLSUser

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # 5 minutes


def _default_limits() -> dict:
    return {
        "tier_id": settings.default_tier,
        "daily_tokens": 10_000,
        "monthly_tokens": 100_000,
        "rpm": 10,
        "rph": 100,
        "tpm": 20_000,
        "concurrent_requests": 3,
    }


async def get_user_limits(user_id: str, db: AsyncSession, redis: Redis) -> dict:
    """Return effective limits for a user (tier base + custom overrides)."""
    cache_key = f"tls:user_limits:{user_id}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    user = await db.get(TLSUser, user_id)
    if not user:
        limits = _default_limits()
    else:
        tier = await db.get(TLSTier, user.tier_id)
        base = dict(tier.limits) if tier else _default_limits()
        base["tier_id"] = user.tier_id
        if user.custom_limits:
            base.update(user.custom_limits)
        limits = base

    await redis.setex(cache_key, CACHE_TTL, json.dumps(limits))
    return limits


async def get_daily_usage(user_id: str, date: str, db: AsyncSession, redis: Redis) -> int:
    """Total tokens consumed today (UTC). Uses Redis cache; falls back to PG."""
    cache_key = f"tls:cache:daily:{user_id}:{date}"
    cached = await redis.get(cache_key)
    if cached:
        return int(cached)

    day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    result = await db.execute(
        select(func.coalesce(func.sum(TLSUsage.tokens_total), 0)).where(
            and_(
                TLSUsage.user_id == user_id,
                TLSUsage.period_start >= day_start,
                TLSUsage.period_start < day_end,
            )
        )
    )
    total: int = result.scalar() or 0
    await redis.setex(cache_key, CACHE_TTL, str(total))
    return total


async def get_monthly_usage(user_id: str, month: str, db: AsyncSession, redis: Redis) -> int:
    """Total tokens consumed this calendar month (UTC)."""
    cache_key = f"tls:cache:monthly:{user_id}:{month}"
    cached = await redis.get(cache_key)
    if cached:
        return int(cached)

    year, mo = int(month[:4]), int(month[5:7])
    month_start = datetime(year, mo, 1, tzinfo=timezone.utc)
    month_end = (
        datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        if mo == 12
        else datetime(year, mo + 1, 1, tzinfo=timezone.utc)
    )

    result = await db.execute(
        select(func.coalesce(func.sum(TLSUsage.tokens_total), 0)).where(
            and_(
                TLSUsage.user_id == user_id,
                TLSUsage.period_start >= month_start,
                TLSUsage.period_start < month_end,
            )
        )
    )
    total: int = result.scalar() or 0
    await redis.setex(cache_key, CACHE_TTL, str(total))
    return total


async def invalidate_user_cache(user_id: str, redis: Redis) -> None:
    await redis.delete(f"tls:user_limits:{user_id}")
