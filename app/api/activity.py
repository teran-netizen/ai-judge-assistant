"""Activity tracking — logs every user action for analytics."""
import logging
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from app.models import User, ActivityLog
from app.database import get_db
from app.utils.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/activity", tags=["activity"])


class ActivityEvent(BaseModel):
    action: str
    details: str = ""
    case_id: Optional[str] = None


@router.post("")
async def log_activity(
    body: ActivityEvent,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Log a user action. Fire-and-forget from frontend."""
    ip = request.headers.get("x-real-ip", request.client.host if request.client else "")
    log = ActivityLog(
        user_id=user.id,
        action=body.action[:50],
        details=(body.details or "")[:500],
        case_id=body.case_id if body.case_id else None,
        ip_address=ip[:45] if ip else None,
    )
    db.add(log)
    # Don't fail the request if logging fails
    try:
        await db.commit()
    except Exception as e:
        logger.warning(f"Activity log failed: {e}")
        await db.rollback()
    return {"ok": True}
