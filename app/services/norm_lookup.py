"""Поиск юридических ссылок в БД legal_norms/legal_documents.

Для каждой ссылки, извлечённой reference_extractor-ом, ищет соответствие в БД.

Стратегии поиска:
  - Кодексы: точное совпадение article + doc_type='codex' + title ILIKE codex_name
  - Пленумы: по номеру + дате из title документа
  - Обзоры практики: по номеру + году из title документа
  - ФЗ/решения ВС: FTS-поиск по тексту (менее точный)
"""
import logging
import re

from sqlalchemy import select, and_, or_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LegalDocument, LegalNorm

logger = logging.getLogger(__name__)

# Маппинг коротких названий кодексов → паттерны для поиска в title документа
CODEX_TITLE_MAP = {
    "ГК": "Гражданский кодекс",
    "ГПК": "Гражданский процессуальный",
    "АПК": "Арбитражный процессуальный",
    "УК": "Уголовный кодекс",
    "УПК": "Уголовно-процессуальный",
    "КоАП": "административных правонарушениях",
    "СК": "Семейный кодекс",
    "ТК": "Трудовой кодекс",
    "КАС": "административного судопроизводства",
    "ЖК": "Жилищный кодекс",
    "ЗК": "Земельный кодекс",
    "НК": "Налоговый кодекс",
    "БК": "Бюджетный кодекс",
    "ВК": "Водный кодекс",
    "ЛК": "Лесной кодекс",
}


# ── Helpers ────────────────────────────────────────────────────

def _found(ref: dict, norm, doc, *, is_active: bool = True, inactive_reason=None) -> dict:
    """Формирует результат 'найдено в БД'."""
    return {
        **ref,
        "db_status": "found",
        "norm_id": str(norm.id) if norm else None,
        "norm_text": norm.text[:1000] if norm and norm.text else None,
        "doc_title": doc.title if doc else None,
        "is_active": is_active,
        "inactive_reason": inactive_reason if not is_active else None,
    }


def _not_found(ref: dict) -> dict:
    """Формирует результат 'не найдено в БД'."""
    return {
        **ref,
        "db_status": "not_found",
        "norm_id": None,
        "norm_text": None,
        "doc_title": None,
        "is_active": True,
    }


async def _find_norm_in_doc(
    doc: LegalDocument,
    paragraph: str | None,
    db: AsyncSession,
) -> LegalNorm | None:
    """Ищет норму (пункт) внутри документа, или возвращает первую норму."""
    if paragraph:
        article_ref = f"п. {paragraph}"
        norm = (await db.execute(
            select(LegalNorm)
            .where(LegalNorm.document_id == doc.id, LegalNorm.article == article_ref)
            .limit(1)
        )).scalar_one_or_none()
        if norm:
            return norm

    # Пункт не указан или не найден — первая норма как представитель
    return (await db.execute(
        select(LegalNorm)
        .where(LegalNorm.document_id == doc.id)
        .order_by(LegalNorm.article)
        .limit(1)
    )).scalar_one_or_none()


# ── Lookup strategies ──────────────────────────────────────────

async def _lookup_codex_ref(ref: dict, db: AsyncSession) -> dict:
    """Поиск ссылки на статью кодекса в БД."""
    codex_short = ref.get("codex", "")
    article_num = ref.get("article", "")

    if not codex_short or not article_num:
        return _not_found(ref)

    title_pattern = CODEX_TITLE_MAP.get(codex_short, codex_short)

    result = (await db.execute(
        select(LegalNorm, LegalDocument)
        .join(LegalDocument, LegalNorm.document_id == LegalDocument.id)
        .where(
            LegalDocument.doc_type == "codex",
            LegalDocument.title.ilike(f"%{title_pattern}%"),
            LegalNorm.article == f"ст. {article_num}",
        )
        .limit(1)
    )).first()

    if result:
        norm, doc = result
        is_active = getattr(norm, "is_active", True)
        return _found(
            ref, norm, doc,
            is_active=is_active,
            inactive_reason=getattr(norm, "inactive_reason", None),
        )

    return _not_found(ref)


async def _lookup_titled_doc_ref(
    ref: dict,
    db: AsyncSession,
    *,
    doc_type: str,
    conditions: list,
) -> dict:
    """Общий поиск для пленумов и обзоров практики.

    Алгоритм одинаковый: найти документ по условиям → найти норму (пункт) внутри.
    """
    docs = (await db.execute(
        select(LegalDocument).where(and_(*conditions)).limit(5)
    )).scalars().all()

    if not docs:
        return _not_found(ref)

    doc = docs[0]
    paragraph = ref.get("paragraph")
    norm = await _find_norm_in_doc(doc, paragraph, db)

    if norm:
        is_active = getattr(norm, "is_active", True)
        return _found(
            ref, norm, doc,
            is_active=is_active,
            inactive_reason=getattr(norm, "inactive_reason", None),
        )

    # Документ есть, но норм внутри нет — всё равно считаем found
    return _found(ref, None, doc)


def _number_ilike_conditions(number: str):
    """Условия ILIKE для поиска номера документа в title."""
    return or_(
        LegalDocument.title.ilike(f"%N {number} %"),
        LegalDocument.title.ilike(f"%N {number}\"%"),
        LegalDocument.title.ilike(f"%№ {number} %"),
        LegalDocument.title.ilike(f"%№ {number}\"%"),
        LegalDocument.title.ilike(f"%N{number} %"),
    )


async def _lookup_plenum_ref(ref: dict, db: AsyncSession) -> dict:
    """Поиск ссылки на постановление пленума."""
    number = ref.get("number")
    date = ref.get("date")

    if not number and not date:
        return _not_found(ref)

    conditions = [LegalDocument.doc_type == "plenum"]

    if number and date:
        conditions.append(LegalDocument.title.ilike(f"%{date}%"))
        conditions.append(_number_ilike_conditions(number))
    elif number:
        conditions.append(_number_ilike_conditions(number))
    elif date:
        conditions.append(LegalDocument.title.ilike(f"%{date}%"))

    return await _lookup_titled_doc_ref(ref, db, doc_type="plenum", conditions=conditions)


async def _lookup_practice_review_ref(ref: dict, db: AsyncSession) -> dict:
    """Поиск ссылки на обзор судебной практики."""
    number = ref.get("number", "").strip()
    year = ref.get("year", "")

    if not number or not year:
        return _not_found(ref)

    conditions = [
        LegalDocument.doc_type == "practice_review",
        LegalDocument.title.ilike(f"%({year})%"),
        or_(
            LegalDocument.title.ilike(f"%N {number} %"),
            LegalDocument.title.ilike(f"%N {number}(%"),
            LegalDocument.title.ilike(f"%№ {number} %"),
            LegalDocument.title.ilike(f"%N {number},%"),
            LegalDocument.title.ilike(f"%, {number} %"),
            LegalDocument.title.ilike(f"%, {number}(%"),
        ),
    ]

    return await _lookup_titled_doc_ref(ref, db, doc_type="practice_review", conditions=conditions)


async def _lookup_fts(ref: dict, db: AsyncSession) -> dict:
    """FTS-поиск для ФЗ, решений ВС и прочих ссылок.
    
    Два прохода: AND-логика для точности, OR-логика как fallback.
    Ранжирование по ts_rank — наиболее релевантная норма возвращается первой.
    """
    raw = ref.get("raw", "")
    if not raw or len(raw) < 5:
        return _not_found(ref)

    search_terms = re.sub(r"[^\w\s]", " ", raw)
    search_terms = " & ".join(w for w in search_terms.split() if len(w) > 2)

    results = None

    # Попытка 1: AND-логика (точечный поиск)
    if search_terms:
        try:
            ts_query = func.to_tsquery("russian", search_terms)
            results = (await db.execute(
                select(
                    LegalNorm,
                    LegalDocument,
                    func.ts_rank(LegalNorm.text_tsvector, ts_query).label("rank"),
                )
                .join(LegalDocument, LegalNorm.document_id == LegalDocument.id)
                .where(LegalNorm.text_tsvector.op("@@")(ts_query))
                .order_by(desc("rank"))
                .limit(3)
            )).all()
        except Exception:
            pass

    # Попытка 2: OR-логика (шире, ловит короткие ссылки)
    if not results:
        try:
            ts_query = func.plainto_tsquery("russian", raw)
            results = (await db.execute(
                select(
                    LegalNorm,
                    LegalDocument,
                    func.ts_rank(LegalNorm.text_tsvector, ts_query).label("rank"),
                )
                .join(LegalDocument, LegalNorm.document_id == LegalDocument.id)
                .where(LegalNorm.text_tsvector.op("@@")(ts_query))
                .order_by(desc("rank"))
                .limit(3)
            )).all()
        except Exception:
            pass

    if results:
        norm, doc, rank = results[0]
        is_active = getattr(norm, "is_active", True)
        return _found(
            ref, norm, doc,
            is_active=is_active,
            inactive_reason=getattr(norm, "inactive_reason", None),
        )

    return _not_found(ref)


# ── Lookup dispatcher ──────────────────────────────────────────

# Маппинг type → функция поиска
_LOOKUP_MAP = {
    "codex": _lookup_codex_ref,
    "plenum": _lookup_plenum_ref,
    "plenum_short": _lookup_plenum_ref,
    "practice_review": _lookup_practice_review_ref,
    "vs_decision": _lookup_fts,
    "federal_law": _lookup_fts,
}


async def lookup_references(refs: list[dict], db: AsyncSession) -> list[dict]:
    """Для каждой ссылки ищет соответствие в БД.

    Args:
        refs: Список ссылок из reference_extractor.extract_legal_references()
        db: Async SQLAlchemy session

    Returns:
        Список ссылок, обогащённых полями:
            ref["db_status"] = "found" | "not_found"
            ref["norm_id"] = UUID string | None
            ref["norm_text"] = "текст нормы (до 1000 символов)" | None
            ref["doc_title"] = "Заголовок документа" | None
    """
    enriched = []

    for ref in refs:
        ref_type = ref.get("type", "")
        lookup_fn = _LOOKUP_MAP.get(ref_type, _lookup_fts)

        try:
            result = await lookup_fn(ref, db)
        except Exception as e:
            logger.error("Lookup error for ref '%s': %s", ref.get("raw", "")[:50], e)
            result = _not_found(ref)

        enriched.append(result)

    found = sum(1 for r in enriched if r["db_status"] == "found")
    logger.info("Norm lookup: %d/%d found in DB", found, len(enriched))

    return enriched
