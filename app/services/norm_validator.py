"""
Валидатор ссылок на нормы в сгенерированном тексте.

Парсит [[NORM:<uuid>]] и [[NEED_NORM:<desc>]] маркеры,
сверяет с БД, присваивает статусы: green / yellow / red.

Результат сохраняется в cases.validation_result.
"""

import re
import logging
from uuid import UUID as PyUUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LegalNorm, LegalDocument

logger = logging.getLogger(__name__)

# Regex для маркеров в тексте
# ВАЖНО: [a-fA-F0-9] — DeepSeek может вернуть UUID в любом регистре
NORM_RE = re.compile(r"\[\[NORM:([a-fA-F0-9\-]{36})\]\]")
NEED_NORM_RE = re.compile(r"\[\[NEED_NORM:(.+?)\]\]")

# Порог релевантности (ниже → жёлтый вместо зелёного)
RELEVANCE_THRESHOLD = 0.05


async def validate_references(
    text: str,
    matched_norms: list[dict],
    db: AsyncSession,
) -> dict:
    """
    Валидирует все ссылки [[NORM:...]] и [[NEED_NORM:...]] в тексте.

    Возвращает:
    {
        "references": [
            {
                "norm_id": "uuid",
                "status": "green" | "yellow" | "red",
                "reason": "...",
                "short_ref": "ст. 395 ГК РФ",
                "positions": [123, 456]  # позиции в тексте (start)
            }
        ],
        "need_norms": [
            {"description": "...", "position": 123}
        ],
        "stats": {
            "total": 10,
            "green": 7,
            "yellow": 2,
            "red": 1,
            "need_norms": 0
        }
    }
    """
    # 1. Собираем все [[NORM:id]] маркеры
    norm_matches = list(NORM_RE.finditer(text))
    need_matches = list(NEED_NORM_RE.finditer(text))

    # Маппинг ID → ранги из step2 (matched_norms)
    norm_ranks = {}
    for n in (matched_norms or []):
        nid = n.get("id", "")
        norm_ranks[nid] = n.get("rank", 0)

    # 2. Собираем уникальные norm_id
    unique_ids = set()
    for m in norm_matches:
        try:
            nid = m.group(1).lower()  # normalize
            PyUUID(nid)
            unique_ids.add(nid)
        except ValueError:
            pass  # невалидный UUID → будет red

    # 3. Запрашиваем нормы из БД (батчем)
    db_norms = {}
    if unique_ids:
        rows = (await db.execute(
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
            .where(LegalNorm.id.in_([PyUUID(uid) for uid in unique_ids]))
        )).all()

        for r in rows:
            db_norms[str(r.id)] = {
                "article": r.article,
                "paragraph": r.paragraph,
                "text": r.text,
                "doc_title": r.title,
                "doc_type": r.doc_type,
                "is_active": r.is_active,
                "date_published": str(r.date_published) if r.date_published else None,
                "source_url": r.source_url,
            }

    # 4. Присваиваем статусы
    references = []
    seen_ids = {}  # norm_id → index в references (для агрегации позиций)

    for m in norm_matches:
        norm_id = m.group(1).lower()  # normalize to lowercase for DB lookup
        position = m.start()

        if norm_id in seen_ids:
            # Дополнительная позиция для уже обработанного ID
            references[seen_ids[norm_id]]["positions"].append(position)
            continue

        # Валидация UUID
        try:
            PyUUID(norm_id)
        except ValueError:
            ref = _make_ref(norm_id, "red", "Невалидный UUID", position)
            seen_ids[norm_id] = len(references)
            references.append(ref)
            continue

        norm_data = db_norms.get(norm_id)

        if not norm_data:
            # Не найдено в БД → красный
            ref = _make_ref(norm_id, "red", "Норма не найдена в базе", position)
        elif not norm_data["is_active"]:
            # Документ деактивирован → жёлтый
            short_ref = _build_short_ref(norm_data)
            ref = _make_ref(norm_id, "yellow", "Документ неактивен/устаревший", position, short_ref)
        else:
            # Норма найдена и активна → проверяем релевантность
            rank = norm_ranks.get(norm_id, None)
            short_ref = _build_short_ref(norm_data)

            if norm_id not in norm_ranks:
                # Норма есть в БД, но НЕ была в подборке step2 — модель её "знала" откуда-то ещё
                ref = _make_ref(norm_id, "yellow", "Норма не из подборки поиска (проверьте вручную)", position, short_ref)
            elif rank is not None and rank < RELEVANCE_THRESHOLD:
                ref = _make_ref(norm_id, "yellow", f"Низкая релевантность (rank={rank:.3f})", position, short_ref)
            else:
                ref = _make_ref(norm_id, "green", "OK", position, short_ref)

        seen_ids[norm_id] = len(references)
        references.append(ref)

    # 5. NEED_NORM маркеры → жёлтые
    need_norms = []
    for m in need_matches:
        need_norms.append({
            "description": m.group(1),
            "position": m.start(),
        })

    # 6. Статистика
    stats = {
        "total": len(references),
        "green": sum(1 for r in references if r["status"] == "green"),
        "yellow": sum(1 for r in references if r["status"] == "yellow"),
        "red": sum(1 for r in references if r["status"] == "red"),
        "need_norms": len(need_norms),
    }

    return {
        "references": references,
        "need_norms": need_norms,
        "stats": stats,
    }


def _make_ref(norm_id: str, status: str, reason: str, position: int, short_ref: str = "") -> dict:
    return {
        "norm_id": norm_id,
        "status": status,
        "reason": reason,
        "short_ref": short_ref,
        "positions": [position],
    }


def _build_short_ref(norm_data: dict) -> str:
    """Строит краткую читаемую ссылку: 'ст. 395, п. 1 ГК РФ'"""
    parts = []
    if norm_data.get("article"):
        parts.append(norm_data["article"])
    if norm_data.get("paragraph"):
        parts.append(norm_data["paragraph"])
    title = norm_data.get("doc_title", "")
    if parts:
        return f"{', '.join(parts)} — {title}"
    return title


def render_text_with_refs(text: str, validation_result: dict) -> str:
    """
    Заменяет [[NORM:uuid]] на человекочитаемые ссылки для отображения.
    Используется для final_text / экспорта.
    """
    if not validation_result:
        return text

    ref_map = {}
    for ref in validation_result.get("references", []):
        nid = ref["norm_id"]
        short = ref.get("short_ref", "")
        if short:
            ref_map[nid] = short
        else:
            ref_map[nid] = f"[неизвестная норма {nid[:8]}...]"

    def replacer(m):
        nid = m.group(1).lower()  # normalize: DeepSeek может вернуть UUID в любом регистре
        return ref_map.get(nid, m.group(0))

    result = NORM_RE.sub(replacer, text)
    # Убираем NEED_NORM маркеры → оставляем как читаемый текст
    result = NEED_NORM_RE.sub(r"[требуется уточнение: \1]", result)
    return result
