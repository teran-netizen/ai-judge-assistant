"""Activity logging helper — tracks all user actions."""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import ActivityLog

logger = logging.getLogger(__name__)


async def log_activity(
    db: AsyncSession,
    user_id,
    action: str,
    details: str = None,
    utm_source: str = None,
    ip_address: str = None,
    case_id=None,
):
    """Log a user action. Fire-and-forget, never raises."""
    try:
        entry = ActivityLog(
            user_id=user_id,
            action=action,
            details=details,
            utm_source=utm_source,
            ip_address=ip_address,
            case_id=case_id,
        )
        db.add(entry)
        await db.flush()
    except Exception as e:
        logger.warning("activity log failed: %s", e)
