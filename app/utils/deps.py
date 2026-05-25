from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID as PyUUID
from app.database import get_db
from app.models import User
from app.utils.auth import decode_access_token_full, decode_internal_jwt, is_token_revoked

bearer = HTTPBearer(auto_error=False)
_internal_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Try HttpOnly cookie first, then fall back to Authorization header (for tests)
    token = request.cookies.get("access_token")
    if not token:
        if cred:
            token = cred.credentials
        else:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не авторизован")
    payload = decode_access_token_full(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невалидный токен")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невалидный токен")
    # Валидируем UUID до обращения к БД (защита от InvalidTextRepresentation)
    try:
        PyUUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невалидный токен")
    # Revocation check: logout invalidates all tokens issued before it.
    # Pre-revocation tokens (no iat) treated as iat=0 — always invalidated
    # once user logs out.
    iat = payload.get("iat", 0)
    if await is_token_revoked(user_id, iat):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия завершена")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа")
    return user


async def can_access_case(user_id, case_user_id, db) -> bool:
    """Check if user owns the case or is an assistant of the case owner."""
    if str(user_id) == str(case_user_id):
        return True
    from app.models import JudgeAssistant
    result = await db.execute(
        select(JudgeAssistant).where(
            JudgeAssistant.judge_id == str(case_user_id),
            JudgeAssistant.assistant_id == str(user_id),
        )
    )
    return result.scalar_one_or_none() is not None


async def is_assistant_of(assistant_id, judge_id, db) -> bool:
    """Check if user is an assistant of given judge."""
    from app.models import JudgeAssistant
    result = await db.execute(
        select(JudgeAssistant).where(
            JudgeAssistant.judge_id == str(judge_id),
            JudgeAssistant.assistant_id == str(assistant_id),
        )
    )
    return result.scalar_one_or_none() is not None


async def get_internal_service(
    cred: HTTPAuthorizationCredentials | None = Depends(_internal_bearer),
) -> dict:
    """Validate internal service-to-service JWT (widget-backend → ai-judge).

    Returns the decoded JWT claims dict on success.
    Raises 401 if the token is missing, invalid, or has wrong issuer/audience.
    """
    if not cred:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Service JWT required (Authorization: Bearer <token>)",
        )
    claims = decode_internal_jwt(cred.credentials)
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired service JWT")
    return claims
