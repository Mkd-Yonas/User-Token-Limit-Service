from __future__ import annotations

from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings

COLLECTION = "tls_users"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_user(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    user = await db[COLLECTION].find_one({"_id": user_id})
    if not user:
        user = {"_id": user_id, "tokens_used": 0, "blocked_at": None, "unblocked_at": None}
        await db[COLLECTION].insert_one(user)
    return user


async def _auto_reset_if_due(db: AsyncIOMotorDatabase, user: dict) -> dict:
    """If the reset window has passed, clear the block and return the fresh user doc."""
    unblocked_at = user.get("unblocked_at")
    if unblocked_at and _now() >= unblocked_at:
        fresh = {"tokens_used": 0, "blocked_at": None, "unblocked_at": None}
        await db[COLLECTION].update_one({"_id": user["_id"]}, {"$set": fresh})
        return {**user, **fresh}
    return user


async def check(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    user = await _get_user(db, user_id)
    user = await _auto_reset_if_due(db, user)

    if user.get("blocked_at"):
        return {
            "allowed": False,
            "tokens_used": user["tokens_used"],
            "token_limit": settings.token_limit,
            "unblocked_at": user["unblocked_at"],
            "reason": f"Token limit reached. Access restores at {user['unblocked_at']} UTC.",
        }

    return {
        "allowed": True,
        "tokens_used": user["tokens_used"],
        "token_limit": settings.token_limit,
    }


async def consume(db: AsyncIOMotorDatabase, user_id: str, tokens: int) -> dict:
    user = await _get_user(db, user_id)
    user = await _auto_reset_if_due(db, user)

    if user.get("blocked_at"):
        return {
            "consumed": False,
            "tokens_used": user["tokens_used"],
            "token_limit": settings.token_limit,
            "blocked": True,
            "unblocked_at": user["unblocked_at"],
        }

    new_total = user["tokens_used"] + tokens

    if new_total >= settings.token_limit:
        now = _now()
        unblocked_at = now + timedelta(hours=settings.reset_hours)
        await db[COLLECTION].update_one(
            {"_id": user_id},
            {"$set": {"tokens_used": new_total, "blocked_at": now, "unblocked_at": unblocked_at}},
        )
        return {
            "consumed": True,
            "tokens_used": new_total,
            "token_limit": settings.token_limit,
            "blocked": True,
            "unblocked_at": unblocked_at,
        }

    await db[COLLECTION].update_one(
        {"_id": user_id},
        {"$set": {"tokens_used": new_total}},
    )
    return {
        "consumed": True,
        "tokens_used": new_total,
        "token_limit": settings.token_limit,
        "blocked": False,
    }


async def status(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    user = await _get_user(db, user_id)
    user = await _auto_reset_if_due(db, user)
    return {
        "user_id": user_id,
        "tokens_used": user["tokens_used"],
        "token_limit": settings.token_limit,
        "blocked": bool(user.get("blocked_at")),
        "blocked_at": user.get("blocked_at"),
        "unblocked_at": user.get("unblocked_at"),
    }


async def admin_reset(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    await db[COLLECTION].update_one(
        {"_id": user_id},
        {"$set": {"tokens_used": 0, "blocked_at": None, "unblocked_at": None}},
        upsert=True,
    )
    return {"reset": True, "user_id": user_id}
