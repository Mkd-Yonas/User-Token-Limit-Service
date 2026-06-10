"""FastAPI application factory with health endpoints, metrics, and reaper scheduler."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, make_asgi_app
from redis.asyncio import Redis

from app.config import settings
from app.dependencies import get_redis_pool
from app.models.schemas import HealthLiveResponse, HealthReadyResponse
from app.routers import admin, limits

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Prometheus metrics ─────────────────────────────────────────────────────────

REQUEST_COUNT = Counter("tls_requests_total", "Total TLS requests", ["endpoint", "result"])
REQUEST_LATENCY = Histogram(
    "tls_request_duration_seconds",
    "TLS request latency",
    ["endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)
REAPER_REAPED = Counter("tls_reaper_reaped_total", "Total stale requests reaped by reaper")

# ── Scheduler ──────────────────────────────────────────────────────────────────

_scheduler = AsyncIOScheduler()


async def _run_reaper() -> None:
    from app.dependencies import _SessionFactory
    from app.services.reaper import reap_stale_requests

    pool = get_redis_pool()
    async with Redis(connection_pool=pool) as redis:
        async with _SessionFactory() as db:
            n = await reap_stale_requests(redis, db)
            if n:
                REAPER_REAPED.inc(n)
                logger.info("Reaper cleaned up %d stale request(s)", n)


# ── App lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _scheduler.add_job(
        _run_reaper,
        "interval",
        minutes=settings.reaper_interval_minutes,
        id="tls_reaper",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("TLS service started — reaper every %d min", settings.reaper_interval_minutes)
    yield
    _scheduler.shutdown(wait=False)
    logger.info("TLS service shutting down")


# ── Application ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Token Limit Service",
        description="Production-grade token quota enforcement sidecar for LLM systems.",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Prometheus metrics endpoint
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    app.include_router(limits.router, prefix="/v1")
    app.include_router(admin.router, prefix="/v1")

    # ── Health ─────────────────────────────────────────────────────────────────

    @app.get("/health/live", response_model=HealthLiveResponse, tags=["health"])
    async def health_live() -> HealthLiveResponse:
        return HealthLiveResponse(status="ok")

    @app.get("/health/ready", response_model=HealthReadyResponse, tags=["health"])
    async def health_ready() -> HealthReadyResponse:
        from app.dependencies import _engine

        pg_status = "ok"
        redis_status = "ok"

        try:
            async with _engine.connect() as conn:
                await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        except Exception as exc:
            pg_status = f"error: {exc}"

        try:
            pool = get_redis_pool()
            async with Redis(connection_pool=pool) as r:
                await r.ping()
        except Exception as exc:
            redis_status = f"error: {exc}"

        overall = "ok" if pg_status == "ok" and redis_status == "ok" else "degraded"
        return HealthReadyResponse(status=overall, postgres=pg_status, redis=redis_status)

    return app


app = create_app()
