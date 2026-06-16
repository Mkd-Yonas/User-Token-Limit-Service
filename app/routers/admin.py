"""Admin endpoint: /admin/reset — manually unblock a user (callable by Spring)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.dependencies import get_db, verify_admin_key
from app.models.schemas import AdminResetRequest, AdminResetResponse
from app.services import limit_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset", response_model=AdminResetResponse, summary="Manually reset a user's token counter and unblock immediately")
async def admin_reset(
    req: AdminResetRequest,
    _key: str = Depends(verify_admin_key),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> AdminResetResponse:
    result = await limit_service.admin_reset(db, req.user_id)
    return AdminResetResponse(**result)
