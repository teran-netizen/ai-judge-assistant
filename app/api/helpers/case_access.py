"""Case access helpers — eliminates repeated select+404 pattern."""
from uuid import UUID as PyUUID
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Case, CaseFile


def _validate_uuid(val: str) -> None:
    """Validate UUID format, raise 400 if invalid."""
    try:
        PyUUID(val)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Невалидный ID")


async def get_case_or_404(
    db: AsyncSession,
    case_id: str,
    user_id,
    *,
    with_files: bool = False,
    with_for_update: bool = False,
) -> Case:
    """Load case by ID + user_id, raise 404 if not found.

    Args:
        with_files: eagerly load case.files relationship
        with_for_update: add FOR UPDATE row lock
    """
    _validate_uuid(case_id)
    stmt = select(Case).where(Case.id == case_id, Case.user_id == user_id)
    if with_files:
        stmt = stmt.options(selectinload(Case.files))
    if with_for_update:
        stmt = stmt.with_for_update()
    case = (await db.execute(stmt)).scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Дело не найдено")
    return case
