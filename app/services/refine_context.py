"""
Smart refine context: подтягивает OCR документов для доработки решения.

Логика:
1. Ключевые типы (иски, отзывы, возражения, договоры) — полный OCR всегда
2. Если всё влезает (<300К символов) — весь OCR целиком
3. Если не влезает — extracted данные из остальных + мини-запрос DeepSeek
   выбирает ещё 1-5 релевантных документов по запросу судьи
"""
import json
import logging
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Типы документов которые ВСЕГДА включаются полным текстом
ALWAYS_FULL_OCR = {
    "claim",            # исковое заявление
    "counter_claim",    # встречный иск
    "defense_response", # отзыв на иск
    "response",         # отзыв/ответ (синоним в текущей БД)
    "objection",        # возражение
    "contract",         # договор
}

MAX_CONTEXT_CHARS = 300_000  # лимит для "всё влезает"
MAX_OCR_PER_DOC = 80_000    # обрезка одного документа
MAX_TOTAL_OCR = 250_000     # лимит суммарного OCR в промпте


async def build_refine_context(
    db: AsyncSession,
    case_id: str,
    case_context: dict | None,
    user_request: str,
) -> str:
    """
    Собирает контекст документов для refine промпта.

    Returns:
        Строка с текстом документов для подстановки в промпт.
        Пустая строка если документов нет.
    """
    if not case_context or not case_context.get("documents"):
        return ""

    documents = case_context.get("documents", [])
    if not documents:
        return ""

    # Загружаем OCR тексты из case_files
    from app.models import CaseFile
    case_files = (await db.execute(
        select(CaseFile).where(CaseFile.case_id == case_id)
    )).scalars().all()

    # Собираем маппинг filename -> ocr_text.
    # Приоритет: case_files.ocr_text (быстрее) → documents[].ocr_text (для новых кейсов).
    ocr_map = {}
    for cf in case_files:
        if cf.ocr_text and len(cf.ocr_text.strip()) > 100:
            ocr_map[cf.filename] = cf.ocr_text
    # Fallback: ищем в case_context.documents (там может быть ocr_text для свежих кейсов)
    if not ocr_map:
        for doc in documents:
            ot = doc.get("ocr_text") or ""
            if ot and len(ot.strip()) > 100:
                ocr_map[doc.get("filename", "")] = ot

    logger.info("[REFINE-CTX] case=%s user_request='%s' total_files=%d files_with_ocr=%d",
                 case_id[:8], user_request[:80], len(case_files), len(ocr_map))

    if not ocr_map:
        # Нет сохранённых OCR текстов — собираем fallback из documents[].extracted
        # (богатые структурированные выжимки от DeepSeek по каждому документу).
        # Это существенно лучше чем короткий case_summary — там полные arguments,
        # key_quotes, стороны, суммы, ссылки на нормы.
        logger.warning(
            "[REFINE-CTX] case=%s NO OCR texts, falling back to extracted per-doc",
            case_id[:8],
        )
        parts = []
        for doc in documents:
            fn = doc.get("filename", "unknown")
            dt = doc.get("doc_type", "other")
            ext = doc.get("extracted")
            if not ext:
                continue
            parts.append(f"=== Документ: {fn} (тип: {dt}) ===")
            if isinstance(ext, dict):
                parts.append(json.dumps(ext, ensure_ascii=False, indent=2))
            else:
                parts.append(str(ext))
            parts.append("")

        if not parts:
            # Совсем ничего нет — последний fallback на summary
            summary = case_context.get("summary", "")
            if isinstance(summary, dict):
                summary = json.dumps(summary, ensure_ascii=False, indent=2)
            return str(summary)

        # Ограничим общий размер чтобы не взорвать промпт
        joined = "\n".join(parts)
        if len(joined) > MAX_TOTAL_OCR:
            joined = joined[:MAX_TOTAL_OCR] + "\n\n[Выжимка обрезана — документ слишком длинный]"
        logger.info(
            "[REFINE-CTX] case=%s extracted-fallback: %d docs, %d chars",
            case_id[:8], len(parts) // 3, len(joined),
        )
        return joined

    # Разделяем документы на ключевые и остальные
    key_docs = []      # всегда полный OCR
    other_docs = []    # extracted или полный OCR если влезает

    for doc in documents:
        doc_type = doc.get("doc_type", "other")
        filename = doc.get("filename", "")
        ocr_text = ocr_map.get(filename, "")

        entry = {
            "filename": filename,
            "doc_type": doc_type,
            "summary_line": doc.get("summary_line", filename),
            "extracted": doc.get("extracted", {}),
            "ocr_text": ocr_text,
            "ocr_chars": len(ocr_text),
        }

        if doc_type in ALWAYS_FULL_OCR:
            key_docs.append(entry)
        else:
            other_docs.append(entry)

    # Логируем ключевые документы
    key_types = [f"{d['doc_type']}:{d['filename'][:30]}({d['ocr_chars']})" for d in key_docs]
    logger.info("[REFINE-CTX] case=%s key_docs=%d types=[%s]", case_id[:8], len(key_docs), ", ".join(key_types[:10]))

    # Считаем общий размер OCR
    total_ocr = sum(d["ocr_chars"] for d in key_docs + other_docs)

    if total_ocr <= MAX_CONTEXT_CHARS:
        # Всё влезает — подставляем полный OCR всех документов
        logger.info("[REFINE-CTX] case=%s ALL docs fit (%d chars, %d docs)",
                     case_id[:8], total_ocr, len(key_docs) + len(other_docs))
        return _format_all_full(key_docs + other_docs)

    # Не влезает — ключевые полностью + мини-запрос для остальных
    key_chars = sum(d["ocr_chars"] for d in key_docs)
    remaining_budget = MAX_TOTAL_OCR - min(key_chars, MAX_TOTAL_OCR - 50_000)

    # Мини-запрос: выбрать релевантные из остальных
    selected_others = await _select_relevant(other_docs, user_request, remaining_budget)

    sel_names = [d["filename"][:30] for d in selected_others]
    logger.info("[REFINE-CTX] case=%s HYBRID: key=%d(%d chars) + selected=%d(%s) + extracted=%d",
                 case_id[:8], len(key_docs), key_chars,
                 len(selected_others), sel_names,
                 len(other_docs) - len(selected_others))

    result = _format_hybrid(key_docs, selected_others, other_docs)
    logger.info("[REFINE-CTX] case=%s RESULT: %d chars for refine prompt", case_id[:8], len(result))
    return result


async def _select_relevant(
    other_docs: list[dict],
    user_request: str,
    budget_chars: int,
) -> list[dict]:
    """DeepSeek мини-запрос: выбрать релевантные документы."""
    if not other_docs or budget_chars <= 0:
        return []

    # Формируем список документов для DeepSeek
    doc_list = "\n".join(
        f"{i+1}. [{d['doc_type']}] {d['filename']} \u2014 {d['summary_line']}"
        for i, d in enumerate(other_docs)
    )

    prompt = (
        f"Запрос судьи: \"{user_request}\"\n\n"
        f"Документы в деле:\n{doc_list}\n\n"
        f"Какие документы (номера) содержат информацию нужную для выполнения запроса?\n"
        f"Ответь JSON массивом номеров. Если документы не нужны \u2014 ответь [].\n"
        f"Выбери максимум 5 самых релевантных."
    )

    try:
        from app.services.deepseek import chat as deepseek_chat
        result = await deepseek_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.0,
        )
        content = result.get("content", "[]")

        # Парсим JSON из ответа
        import re
        match = re.search(r'\[[\d\s,]*\]', content)
        if match:
            indices = json.loads(match.group())
            selected = []
            total = 0
            for idx in indices:
                i = idx - 1  # 1-based -> 0-based
                if 0 <= i < len(other_docs):
                    doc = other_docs[i]
                    if total + doc["ocr_chars"] <= budget_chars:
                        selected.append(doc)
                        total += doc["ocr_chars"]
            logger.info("[REFINE-CTX] Mini-query selected %d docs (%d chars)", len(selected), total)
            return selected
        else:
            logger.warning("[REFINE-CTX] Mini-query returned unparseable: %s", content[:100])
            return []

    except Exception as e:
        logger.warning("[REFINE-CTX] Mini-query failed: %s", e)
        return []


def _format_all_full(docs: list[dict]) -> str:
    """Форматирует все документы с полным OCR."""
    parts = []
    for d in docs:
        ocr = d["ocr_text"]
        if len(ocr) > MAX_OCR_PER_DOC:
            ocr = ocr[:MAX_OCR_PER_DOC] + "\n[...текст обрезан...]"
        parts.append(f"--- {d['filename']} [{d['doc_type']}] ---\n{ocr}")
    return "\n\n".join(parts)


def _format_hybrid(
    key_docs: list[dict],
    selected_others: list[dict],
    all_others: list[dict],
) -> str:
    """Форматирует: ключевые полностью + выбранные полностью + остальные кратко."""
    parts = []

    # Ключевые — полный OCR
    if key_docs:
        parts.append("КЛЮЧЕВЫЕ ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ (полный текст):")
        for d in key_docs:
            ocr = d["ocr_text"]
            if len(ocr) > MAX_OCR_PER_DOC:
                ocr = ocr[:MAX_OCR_PER_DOC] + "\n[...текст обрезан...]"
            parts.append(f"\n--- {d['filename']} [{d['doc_type']}] ---\n{ocr}")

    # Выбранные мини-запросом — полный OCR
    selected_filenames = {d["filename"] for d in selected_others}
    if selected_others:
        parts.append("\nДОПОЛНИТЕЛЬНЫЕ ДОКУМЕНТЫ (полный текст):")
        for d in selected_others:
            ocr = d["ocr_text"]
            if len(ocr) > MAX_OCR_PER_DOC:
                ocr = ocr[:MAX_OCR_PER_DOC] + "\n[...текст обрезан...]"
            parts.append(f"\n--- {d['filename']} [{d['doc_type']}] ---\n{ocr}")

    # Остальные — только extracted данные
    remaining = [d for d in all_others if d["filename"] not in selected_filenames]
    if remaining:
        parts.append("\nОСТАЛЬНЫЕ ДОКУМЕНТЫ (краткие данные):")
        for d in remaining:
            ext = d.get("extracted", {})
            summary = d.get("summary_line", d["filename"])
            ext_text = json.dumps(ext, ensure_ascii=False, indent=2) if ext else summary
            # Ограничиваем extracted до 2000 символов на документ
            if len(ext_text) > 2000:
                ext_text = ext_text[:2000] + "..."
            parts.append(f"\n[{d['doc_type']}] {d['filename']}: {ext_text}")

    return "\n".join(parts)
