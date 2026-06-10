"""Admin endpoints: /admin/limits, /admin/refill, /admin/tiers."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_redis, verify_admin_key
from app.models.database import TLSLimitChange, TLSTier, TLSUser
from app.models.schemas import (
    AdminRefillRequest,
    AdminRefillResponse,
    AdminSetLimitsRequest,
    AdminSetLimitsResponse,
    TierCreate,
    TierResponse,
)
from app.services.quota_service import invalidate_user_cache

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/limits", response_model=AdminSetLimitsResponse, summary="Set / override limits for a user or org")
async def admin_set_limits(
    req: AdminSetLimitsRequest,
    _key: str = Depends(verify_admin_key),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AdminSetLimitsResponse:
    if not req.user_id and not req.org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id or org_id required")

    now = datetime.now(timezone.utc)

    if req.user_id:
        user = await db.get(TLSUser, req.user_id)
        if not user:
            user = TLSUser(
                user_id=req.user_id,
                custom_limits=req.limits,
                created_at=now,
                updated_at=now,
            )
            db.add(user)
        else:
            old_limits = dict(user.custom_limits or {})
            user.custom_limits = {**(user.custom_limits or {}), **req.limits}
            user.updated_at = now

            audit = TLSLimitChange(
                user_id=req.user_id,
                changed_by=req.changed_by,
                old_limits=old_limits,
                new_limits=user.custom_limits,
                reason=req.reason,
                created_at=now,
            )
            db.add(audit)

        await db.commit()
        await invalidate_user_cache(str(req.user_id), redis)

    return AdminSetLimitsResponse(
        updated=True,
        user_id=req.user_id,
        org_id=req.org_id,
        new_limits=req.limits,
    )


@router.post("/refill", response_model=AdminRefillResponse, summary="Add token credits to a user")
async def admin_refill(
    req: AdminRefillRequest,
    _key: str = Depends(verify_admin_key),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AdminRefillResponse:
    now = datetime.now(timezone.utc)
    user = await db.get(TLSUser, req.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hard_balance = (user.hard_balance or 0) + req.tokens
    user.updated_at = now

    audit = TLSLimitChange(
        user_id=req.user_id,
        changed_by=req.changed_by,
        reason=req.reason or f"Refill +{req.tokens} tokens",
        created_at=now,
    )
    db.add(audit)
    await db.commit()
    await invalidate_user_cache(str(req.user_id), redis)

    return AdminRefillResponse(
        refilled=True,
        user_id=req.user_id,
        tokens_added=req.tokens,
        new_balance=user.hard_balance,
    )


@router.get("/tiers", response_model=list[TierResponse], summary="List all tiers")
async def admin_list_tiers(
    _key: str = Depends(verify_admin_key),
    db: AsyncSession = Depends(get_db),
) -> list[TierResponse]:
    result = await db.execute(select(TLSTier).order_by(TLSTier.tier_id))
    tiers = result.scalars().all()
    return [
        TierResponse(
            tier_id=t.tier_id,
            name=t.name,
            limits=t.limits,
            cost_multiplier=float(t.cost_multiplier),
            is_active=t.is_active,
        )
        for t in tiers
    ]


@router.post("/tiers", response_model=TierResponse, status_code=status.HTTP_201_CREATED, summary="Create or update a tier")
async def admin_upsert_tier(
    req: TierCreate,
    _key: str = Depends(verify_admin_key),
    db: AsyncSession = Depends(get_db),
) -> TierResponse:
    existing = await db.get(TLSTier, req.tier_id)
    if existing:
        existing.name = req.name
        existing.limits = req.limits
        existing.cost_multiplier = req.cost_multiplier
        existing.is_active = req.is_active
        tier = existing
    else:
        tier = TLSTier(
            tier_id=req.tier_id,
            name=req.name,
            limits=req.limits,
            cost_multiplier=req.cost_multiplier,
            is_active=req.is_active,
        )
        db.add(tier)

    await db.commit()
    return TierResponse(
        tier_id=tier.tier_id,
        name=tier.name,
        limits=tier.limits,
        cost_multiplier=float(tier.cost_multiplier),
        is_active=tier.is_active,
    )
