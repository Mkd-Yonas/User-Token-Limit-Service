"""Public limit endpoints: /limits/check, /limits/consume, /limits/usage, /limits/history."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_redis, verify_api_key
from app.models.database import TLSUsage
from app.models.schemas import (
    CheckAllowedResponse,
    CheckBlockedResponse,
    CheckRequest,
    ConsumeRequest,
    ConsumeResponse,
    HistoryRecord,
    HistoryResponse,
    UsageResponse,
)
from app.services.limit_checker import check_limits
from app.services.limit_consumer import consume_tokens
from app.services.quota_service import get_daily_usage, get_monthly_usage, get_user_limits

router = APIRouter(prefix="/limits", tags=["limits"])


@router.post("/check", summary="Pre-flight quota check")
async def limits_check(
    req: CheckRequest,
    _key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    allowed, payload = await check_limits(req, db, redis)
    if allowed:
        return CheckAllowedResponse(**payload)
    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=payload)


@router.post("/consume", response_model=ConsumeResponse, summary="Post-flight token deduction")
async def limits_consume(
    req: ConsumeRequest,
    _key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> ConsumeResponse:
    result = await consume_tokens(req, db, redis)
    return ConsumeResponse(**result)


@router.get("/usage", response_model=UsageResponse, summary="Current period usage for a user")
async def limits_usage(
    user_id: uuid.UUID = Query(...),
    _key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> UsageResponse:
    now_utc = datetime.now(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    month = now_utc.strftime("%Y-%m")
    uid = str(user_id)

    limits = await get_user_limits(uid, db, redis)
    daily_used = await get_daily_usage(uid, today, db, redis)
    monthly_used = await get_monthly_usage(uid, month, db, redis)

    tomorrow = (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    return UsageResponse(
        user_id=user_id,
        tier=limits.get("tier_id", "free"),
        daily_used=daily_used,
        daily_limit=limits.get("daily_tokens"),
        monthly_used=monthly_used,
        monthly_limit=limits.get("monthly_tokens"),
        resets_at=tomorrow.isoformat(),
        period_date=today,
    )


@router.get("/history", response_model=HistoryResponse, summary="Paginated usage history")
async def limits_history(
    user_id: uuid.UUID = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    offset = (page - 1) * page_size

    count_result = await db.execute(
        select(func.count()).select_from(TLSUsage).where(TLSUsage.user_id == user_id)
    )
    total: int = count_result.scalar() or 0

    rows_result = await db.execute(
        select(TLSUsage)
        .where(TLSUsage.user_id == user_id)
        .order_by(TLSUsage.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = rows_result.scalars().all()

    records = [
        HistoryRecord(
            request_id=r.request_id,
            tokens_input=r.tokens_input,
            tokens_output=r.tokens_output,
            tokens_total=r.tokens_total,
            model_id=r.model_id,
            created_at=r.created_at.isoformat(),
            metadata=r.metadata_,
        )
        for r in rows
    ]

    return HistoryResponse(
        user_id=user_id,
        page=page,
        page_size=page_size,
        total=total,
        records=records,
    )
