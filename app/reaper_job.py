"""Standalone reaper entrypoint for K8s CronJob (Option A from spec)."""

import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.services.reaper import reap_stale_requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(settings.redis_url)

    try:
        async with factory() as db:
            n = await reap_stale_requests(redis, db)
            logger.info("Reaper finished: %d stale request(s) cleaned up", n)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
