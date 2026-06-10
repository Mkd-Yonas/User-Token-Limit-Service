"""FastAPI dependency injection: DB session, Redis, API key auth."""

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from redis.asyncio import Redis, ConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# ── PostgreSQL ────────────────────────────────────────────────────────────────

_engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)
_SessionFactory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _SessionFactory() as session:
        yield session


# ── Redis ─────────────────────────────────────────────────────────────────────

_redis_pool: ConnectionPool | None = None


def get_redis_pool() -> ConnectionPool:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = ConnectionPool.from_url(settings.redis_url, decode_responses=False)
    return _redis_pool


async def get_redis() -> AsyncGenerator[Redis, None]:
    pool = get_redis_pool()
    async with Redis(connection_pool=pool) as client:
        yield client


# ── Auth ──────────────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


def _extract_key(raw: str | None) -> str:
    if raw and raw.startswith("Bearer "):
        return raw[7:]
    return raw or ""


async def verify_api_key(raw: str | None = Security(_api_key_header)) -> str:
    key = _extract_key(raw)
    if key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return key


async def verify_admin_key(raw: str | None = Security(_api_key_header)) -> str:
    key = _extract_key(raw)
    if key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")
    return key
