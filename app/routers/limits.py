"""Public endpoints: /limits/check, /limits/consume, /limits/status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.dependencies import get_db, verify_api_key
from app.models.schemas import (
    CheckRequest, CheckResponse,
    ConsumeRequest, ConsumeResponse,
    StatusResponse,
)
from app.services import limit_service

router = APIRouter(prefix="/limits", tags=["limits"])


@router.post("/check", response_model=CheckResponse, summary="Pre-flight quota check")
async def limits_check(
    req: CheckRequest,
    _key: str = Depends(verify_api_key),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> CheckResponse:
    result = await limit_service.check(db, req.user_id)
    if not result["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=result,
        )
    return CheckResponse(**result)


@router.post("/consume", response_model=ConsumeResponse, summary="Post-flight token deduction")
async def limits_consume(
    req: ConsumeRequest,
    _key: str = Depends(verify_api_key),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> ConsumeResponse:
    result = await limit_service.consume(db, req.user_id, req.tokens)
    return ConsumeResponse(**result)


@router.get("/status", response_model=StatusResponse, summary="Current token status for a user")
async def limits_status(
    user_id: str = Query(...),
    _key: str = Depends(verify_api_key),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> StatusResponse:
    result = await limit_service.status(db, user_id)
    return StatusResponse(**result)
