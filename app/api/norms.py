"""
API для получения информации о нормах права.
Используется фронтендом для hover-попапов в тексте решения.
"""

import re
from uuid import UUID as PyUUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import LegalNorm, LegalDocument
from app.utils.deps import get_current_user

router = APIRouter(prefix="/api/norms", tags=["norms"])


def _build_article_url(source_url: str, article: str, doc_type: str) -> str:
    """Построить прямую ссылку на статью/пункт нормы.

    Для кодексов: zakonrf.info/gpk/ + "135" → zakonrf.info/gpk/135/
    Для остальных: source_url уже ведёт на конкретный документ.
    """
    if not source_url:
        return ""

    # Для кодексов — конструируем ссылку на статью
    if doc_type == "codex" and "zakonrf.info" in source_url:
        # "ст. 135" → "135", "ст. 1.1" → "1.1"
        m = re.search(r"ст\.\s*(\S+)", article or "")
        if m:
            num = m.group(1)
            # source_url = "https://www.zakonrf.info/gpk/"
            base = source_url.rstrip("/")
            return f"{base}/{num}/"

    return source_url


@router.get("/{norm_id}")
async def get_norm(
    norm_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Возвращает полную информацию о норме для hover-попапа.
    Фронтенд запрашивает при наведении на [[NORM:uuid]] чип.
    """
    try:
        uid = PyUUID(norm_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Невалидный ID нормы")

    row = (await db.execute(
        select(
            LegalNorm.id,
            LegalNorm.article,
            LegalNorm.paragraph,
            LegalNorm.text,
            LegalDocument.title,
            LegalDocument.doc_type,
            LegalDocument.is_active,
            LegalDocument.date_published,
            LegalDocument.source_url,
        )
        .join(LegalDocument, LegalDocument.id == LegalNorm.document_id)
        .where(LegalNorm.id == uid)
    )).one_or_none()

    if not row:
        raise HTTPException(404, "Норма не найдена")

    # Прямая ссылка на статью (для кодексов — на конкретную статью)
    article_url = _build_article_url(
        row.source_url or "", row.article or "", row.doc_type or ""
    )

    return {
        "id": str(row.id),
        "article": row.article or "",
        "paragraph": row.paragraph or "",
        "text": row.text,
        "doc_title": row.title,
        "doc_type": row.doc_type,
        "is_active": row.is_active,
        "date_published": str(row.date_published) if row.date_published else None,
        "source_url": article_url,
    }
