from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings

# ── MongoDB ───────────────────────────────────────────────────────────────────

_db: AsyncIOMotorDatabase | None = None


def set_db(db: AsyncIOMotorDatabase) -> None:
    global _db
    _db = db


def get_db() -> AsyncIOMotorDatabase:
    return _db


# ── Auth ──────────────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


def _extract_key(raw: str | None) -> str:
    if raw and raw.startswith("Bearer "):
        return raw[7:]
    return raw or ""


async def verify_api_key(raw: str | None = Security(_api_key_header)) -> str:
    if _extract_key(raw) != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return raw


async def verify_admin_key(raw: str | None = Security(_api_key_header)) -> str:
    if _extract_key(raw) != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")
    return raw
