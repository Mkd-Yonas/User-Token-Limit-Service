"""Shared pytest fixtures using fakeredis and an in-memory SQLite-compatible async DB."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app
from app.models.database import Base

# Use aiosqlite for tests (no PostgreSQL required)
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DB_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def redis():
    import fakeredis.aioredis as fakeredis
    r = fakeredis.FakeRedis()
    yield r
    await r.flushall()
    await r.aclose()


@pytest_asyncio.fixture
async def client(db, redis):
    app = create_app()

    async def override_db():
        yield db

    async def override_redis():
        yield redis

    from app.dependencies import get_db, get_redis
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = override_redis

    from app.config import settings
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as c:
        yield c
