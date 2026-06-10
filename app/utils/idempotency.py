"""Request-ID deduplication helpers backed by Redis."""

from redis.asyncio import Redis

PENDING_SET_KEY = "tls:pending_set"
FINALIZED_TTL = 86_400  # 24 hours


async def is_request_pending(request_id: str, redis: Redis) -> bool:
    score = await redis.zscore(PENDING_SET_KEY, request_id)
    return score is not None


async def is_request_finalized(request_id: str, redis: Redis) -> bool:
    val = await redis.get(f"tls:finalized:{request_id}")
    return val is not None


async def mark_request_finalized(request_id: str, redis: Redis) -> None:
    await redis.setex(f"tls:finalized:{request_id}", FINALIZED_TTL, "1")
