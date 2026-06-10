"""Stale request reaper — spec section 8.2.

Runs on a schedule (APScheduler or K8s CronJob).
Finds pending request_ids older than the configured threshold, verifies they
were not already consumed (idempotency), then releases the concurrent slot
and refunds reserved tokens.
"""

from __future__ import annotations

import logging
import time

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import TLSUsage
from app.services.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

PENDING_SET_KEY = "tls:pending_set"


async def reap_stale_requests(redis: Redis, db: AsyncSession) -> int:
    """Reap all pending requests older than the stale threshold.

    Returns the number of requests reaped.
    """
    threshold_seconds = settings.reaper_stale_threshold_minutes * 60
    cutoff = time.time() - threshold_seconds

    stale: list[bytes] = await redis.zrangebyscore(PENDING_SET_KEY, 0, cutoff)
    if not stale:
        return 0

    reaped = 0
    rate = RateLimiter(redis)

    for raw_id in stale:
        request_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id

        # Idempotency: skip if already finalized
        if await redis.get(f"tls:finalized:{request_id}"):
            await redis.zrem(PENDING_SET_KEY, request_id)
            continue

        # Check DB: was it consumed but finalization key expired?
        result = await db.execute(
            select(TLSUsage.id).where(TLSUsage.request_id == request_id).limit(1)
        )
        if result.scalar():
            logger.info("Reaper: %s already in DB, skipping refund", request_id)
            await redis.zrem(PENDING_SET_KEY, request_id)
            continue

        # Retrieve pending metadata
        pending_key = f"tls:pending:{request_id}"
        data = await redis.hgetall(pending_key)
        if not data:
            await redis.zrem(PENDING_SET_KEY, request_id)
            continue

        user_id = (data.get(b"user_id") or b"").decode()
        reserved = int(data.get(b"tokens", 0))
        date = (data.get(b"date") or b"").decode()

        async with redis.pipeline(transaction=True) as pipe:
            if reserved and date and user_id:
                pipe.decrby(f"tls:pending_tokens:{user_id}:{date}", reserved)
            pipe.delete(pending_key)
            pipe.zrem(PENDING_SET_KEY, request_id)
            await pipe.execute()

        if user_id:
            await rate.decrement_concurrent(user_id)

        logger.warning("Reaped stale request: %s (user=%s reserved=%d)", request_id, user_id, reserved)
        reaped += 1

    return reaped
