"""Redis-backed sliding-window rate limiter with atomic Lua operations."""

from __future__ import annotations

import time

from redis.asyncio import Redis

# Atomic sliding-window request counter.
# Uses a sorted set keyed by timestamp; removes expired members before checking.
_SLIDING_WINDOW_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
    return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window + 1)
return 1
"""


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    # ── Requests per minute ────────────────────────────────────────────────────

    async def check_rpm(self, user_id: str, limit: int) -> bool:
        now = time.time()
        result = await self.redis.eval(
            _SLIDING_WINDOW_LUA,
            1,
            f"tls:rpm:{user_id}",
            now,
            60,
            limit,
            f"{now}:{user_id}",
        )
        return bool(result)

    # ── Requests per hour ──────────────────────────────────────────────────────

    async def check_rph(self, user_id: str, limit: int) -> bool:
        now = time.time()
        result = await self.redis.eval(
            _SLIDING_WINDOW_LUA,
            1,
            f"tls:rph:{user_id}",
            now,
            3600,
            limit,
            f"{now}:{user_id}",
        )
        return bool(result)

    # ── Tokens per minute ──────────────────────────────────────────────────────
    # Bucket per 60-second wall-clock minute for simplicity; atomic INCRBY.

    async def check_tpm(self, user_id: str, tokens: int, limit: int) -> bool:
        bucket = int(time.time()) // 60
        key = f"tls:tpm:{user_id}:{bucket}"
        new_total = await self.redis.incrby(key, tokens)
        if new_total == tokens:
            await self.redis.expire(key, 120)
        return new_total <= limit

    # ── Concurrent requests ────────────────────────────────────────────────────

    async def get_concurrent(self, user_id: str) -> int:
        val = await self.redis.get(f"tls:concurrent:{user_id}")
        return int(val) if val else 0

    async def increment_concurrent(self, user_id: str) -> int:
        key = f"tls:concurrent:{user_id}"
        val = await self.redis.incr(key)
        await self.redis.expire(key, 600)
        return val

    async def decrement_concurrent(self, user_id: str) -> None:
        key = f"tls:concurrent:{user_id}"
        val = await self.redis.decr(key)
        if val < 0:
            await self.redis.set(key, 0)
