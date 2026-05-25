import logging
from uuid import UUID as PyUUID
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, Case, CaseFile, CaseUploadSession
from app.utils.deps import get_current_user
from app.api.helpers.case_access import get_case_or_404, _validate_uuid

router = APIRouter(prefix="/api/cases", tags=["upload-sessions"])
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════

class CreateUploadSessionRequest(BaseModel):
    expected_files_count: Optional[int] = Field(default=None, ge=1)
    total_bytes: Optional[int] = Field(default=None, ge=0)

class UploadSessionResponse(BaseModel):
    id: str
    case_id: str
    status: str
    expected_files_count: Optional[int] = None
    uploaded_files_count: int = 0
    total_bytes: Optional[int] = None
    uploaded_bytes: int = 0
    failed_files_count: int = 0
    started_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    finalized_at: Optional[datetime] = None

class UploadStateResponse(BaseModel):
    session_id: Optional[str] = None
    status: Optional[str] = None
    expected_files_count: Optional[int] = None
    uploaded_files_count: int = 0
    uploaded_bytes: int = 0
    total_files: int = 0
    accepted_file_ids: list[str] = []
    accepted_client_file_ids: list[str] = []


# ═══════════════════════════════════════════════════════════════
# POST /api/cases/{case_id}/upload-sessions — create upload session
# ═══════════════════════════════════════════════════════════════

@router.post("/{case_id}/upload-sessions")
async def create_upload_session(
    case_id: str,
    body: CreateUploadSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_uuid(case_id)
    case = await get_case_or_404(db, case_id, user.id)

    if case.status == "processing":
        raise HTTPException(409, "Нельзя начинать загрузку — дело обрабатывается")

    # Don't cancel existing sessions - their files are already uploaded
    # Just let the new session track additional files

    session = CaseUploadSession(
        case_id=case.id,
        user_id=user.id,
        status="pending",
        expected_files_count=body.expected_files_count,
        total_bytes=body.total_bytes,
    )
    db.add(session)
    await db.flush()

    logger.info(
        "upload_session created: session=%s case=%s user=%s expected=%s",
        session.id, case_id, user.id, body.expected_files_count,
    )

    return UploadSessionResponse(
        id=str(session.id),
        case_id=str(session.case_id),
        status=session.status,
        expected_files_count=session.expected_files_count,
        uploaded_files_count=session.uploaded_files_count,
        total_bytes=session.total_bytes,
        uploaded_bytes=session.uploaded_bytes,
        failed_files_count=session.failed_files_count,
        started_at=session.started_at,
        last_activity_at=session.last_activity_at,
        finalized_at=session.finalized_at,
    )


# ═══════════════════════════════════════════════════════════════
# GET /api/cases/{case_id}/upload-state — resume state
# ═══════════════════════════════════════════════════════════════

@router.get("/{case_id}/upload-state")
async def get_upload_state(
    case_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_uuid(case_id)
    case = await get_case_or_404(db, case_id, user.id)

    # Find latest active upload session
    session = (await db.execute(
        select(CaseUploadSession).where(
            CaseUploadSession.case_id == case.id,
            CaseUploadSession.status.in_(["pending", "uploading"]),
        ).order_by(CaseUploadSession.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    # Total files in this case (across all sessions)
    total_files = (await db.execute(
        select(func.count()).where(CaseFile.case_id == case.id)
    )).scalar() or 0

    if not session:
        return UploadStateResponse(total_files=total_files)

    # Get accepted files for this session
    accepted = (await db.execute(
        select(CaseFile).where(
            CaseFile.case_id == case.id,
            CaseFile.upload_session_id == session.id,
        )
    )).scalars().all()

    return UploadStateResponse(
        session_id=str(session.id),
        status=session.status,
        expected_files_count=session.expected_files_count,
        uploaded_files_count=session.uploaded_files_count,
        uploaded_bytes=session.uploaded_bytes,
        total_files=total_files,
        accepted_file_ids=[str(f.id) for f in accepted],
        accepted_client_file_ids=[f.client_file_id for f in accepted if f.client_file_id],
    )


# ═══════════════════════════════════════════════════════════════
# POST /api/cases/{case_id}/upload-sessions/{session_id}/finalize
# ═══════════════════════════════════════════════════════════════

@router.post("/{case_id}/upload-sessions/{session_id}/finalize")
async def finalize_upload_session(
    case_id: str,
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_uuid(case_id)
    _validate_uuid(session_id)

    session = (await db.execute(
        select(CaseUploadSession).where(
            CaseUploadSession.id == session_id,
            CaseUploadSession.case_id == case_id,
            CaseUploadSession.user_id == user.id,
        )
    )).scalar_one_or_none()

    if not session:
        raise HTTPException(404, "Сессия загрузки не найдена")

    if session.status == "finalized":
        return UploadSessionResponse(
            id=str(session.id),
            case_id=str(session.case_id),
            status=session.status,
            expected_files_count=session.expected_files_count,
            uploaded_files_count=session.uploaded_files_count,
            total_bytes=session.total_bytes,
            uploaded_bytes=session.uploaded_bytes,
            failed_files_count=session.failed_files_count,
            started_at=session.started_at,
            last_activity_at=session.last_activity_at,
            finalized_at=session.finalized_at,
        )

    if session.status not in ("pending", "uploading"):
        raise HTTPException(409, f"Нельзя финализировать сессию в статусе {session.status}")

    # Validate completeness
    if session.expected_files_count is not None:
        if session.uploaded_files_count < session.expected_files_count:
            raise HTTPException(409,
                f"Загрузка не завершена: {session.uploaded_files_count}/{session.expected_files_count} файлов. "
                f"Догрузите оставшиеся файлы перед генерацией."
            )
    if session.failed_files_count > 0:
        logger.warning("finalize with %d failed files, session=%s", session.failed_files_count, session_id)

    now = datetime.now(timezone.utc)
    session.status = "finalized"
    session.finalized_at = now
    session.last_activity_at = now
    session.updated_at = now

    logger.info(
        "upload_session finalized: session=%s case=%s uploaded=%d/%s",
        session.id, case_id, session.uploaded_files_count, session.expected_files_count,
    )

    return UploadSessionResponse(
        id=str(session.id),
        case_id=str(session.case_id),
        status=session.status,
        expected_files_count=session.expected_files_count,
        uploaded_files_count=session.uploaded_files_count,
        total_bytes=session.total_bytes,
        uploaded_bytes=session.uploaded_bytes,
        failed_files_count=session.failed_files_count,
        started_at=session.started_at,
        last_activity_at=session.last_activity_at,
        finalized_at=session.finalized_at,
    )
