from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.dependencies import set_db
from app.models.schemas import HealthLiveResponse, HealthReadyResponse
from app.routers import admin, limits

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_mongo_client: AsyncIOMotorClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mongo_client
    _mongo_client = AsyncIOMotorClient(settings.mongo_url, tz_aware=True)
    set_db(_mongo_client[settings.mongo_db])
    logger.info("TQS service started — MongoDB: %s / %s", settings.mongo_url, settings.mongo_db)
    yield
    _mongo_client.close()
    logger.info("TQS service stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Token Quota Service",
        description="Token usage enforcement for LLM systems.",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(limits.router, prefix="/v1")
    app.include_router(admin.router, prefix="/v1")

    @app.get("/health/live", response_model=HealthLiveResponse, tags=["health"])
    async def health_live() -> HealthLiveResponse:
        return HealthLiveResponse(status="ok")

    @app.get("/health/ready", response_model=HealthReadyResponse, tags=["health"])
    async def health_ready() -> HealthReadyResponse:
        mongo_status = "ok"
        try:
            await _mongo_client.admin.command("ping")
        except Exception as exc:
            mongo_status = f"error: {exc}"

        overall = "ok" if mongo_status == "ok" else "degraded"
        return HealthReadyResponse(status=overall, mongodb=mongo_status)

    return app


app = create_app()
