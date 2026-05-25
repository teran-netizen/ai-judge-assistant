"""
Модуль 2: Context — хранение и управление контекстом дела.

CRUD для case_context JSONB:
- empty_context() — пустая структура
- add_document() — добавить документ + обновить summary
- remove_document() — удалить документ + пересчитать summary
- is_duplicate() — проверка дубликатов по хешу OCR-текста
- build_brief_summary() — краткий текст для промпта (делегирует в extract_prompts)
"""

import json
import re
import logging
from datetime import datetime, timezone

from app.services.deepseek import deepseek
from app.services.extract_prompts import (
    build_summary_update_messages,
    build_brief_summary,
)

logger = logging.getLogger(__name__)


def empty_context() -> dict:
    """Возвращает пустую структуру case_context."""
    return {
        "documents": [],
        "summary": {},
        "doc_count": 0,
        "total_chars": 0,
    }


def is_duplicate(case_context: dict, ocr_text_hash: str) -> str | None:
    """
    Проверяет, есть ли документ с таким же хешем OCR-текста.

    Returns:
        filename дубликата, если найден, иначе None.
    """
    if not case_context or not case_context.get("documents"):
        return None
    for doc in case_context["documents"]:
        if doc.get("ocr_text_hash") == ocr_text_hash:
            return doc.get("filename", "unknown")
    return None


async def add_document(
    case_context: dict,
    extracted: dict,
    filename: str,
    ocr_text_hash: str,
    ocr_chars: int = 0,
    ocr_text: str = "",
    skip_summary: bool = False,
    file_path: str = None,
) -> dict:
    """
    Добавляет обработанный документ в case_context и обновляет summary.

    Args:
        case_context: текущий контекст (мутируется и возвращается)
        extracted: результат извлечения из документа (JSON от DeepSeek)
        filename: имя файла
        ocr_text_hash: SHA-256 хеш OCR-текста
        ocr_chars: количество символов OCR-текста
        skip_summary: если True — пропустить обновление summary через DeepSeek
                      (используется при пакетной обработке для ускорения,
                       summary компилируется один раз в конце батча)

    Returns:
        Обновлённый case_context
    """
    if not case_context:
        case_context = empty_context()

    doc_type = extracted.get("doc_type", "other")
    summary_line = extracted.get("summary_line", filename)

    # Добавляем документ в список
    doc_entry = {
        "doc_index": case_context["doc_count"],
        "doc_type": doc_type,
        "filename": filename,
        "file_path": file_path,
        "summary_line": summary_line,
        "extracted": extracted,
        "ocr_text_hash": ocr_text_hash,
        "ocr_text": ocr_text,
        "ocr_chars": ocr_chars,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    case_context["documents"].append(doc_entry)
    case_context["doc_count"] = len(case_context["documents"])
    case_context["total_chars"] = sum(
        d.get("ocr_chars", 0) for d in case_context["documents"]
    )

    if skip_summary:
        # Пропускаем DeepSeek — summary будет скомпилирован в конце батча
        return case_context

    # Обновляем summary через DeepSeek
    try:
        current_summary = case_context.get("summary", {})
        messages = build_summary_update_messages(
            current_summary=current_summary,
            extracted_data=extracted,
            doc_type=doc_type,
            filename=filename,
        )
        result = await deepseek.chat(messages, max_tokens=4096, temperature=0.1)
        content = result["content"]

        # Парсим JSON из ответа
        new_summary = _parse_json_response(content)
        if new_summary:
            case_context["summary"] = new_summary
        else:
            logger.warning(f"Не удалось распарсить summary update для {filename}")

    except Exception as e:
        logger.error(f"Ошибка обновления summary для {filename}: {e}")
        # Summary не обновился, но документ добавлен — это OK

    return case_context


async def compile_summary(case_context: dict) -> dict:
    """
    Компилирует summary из всех документов в case_context за ОДИН вызов DeepSeek.

    Используется в конце пакетной обработки вместо инкрементального обновления
    summary после каждого документа (что требовало N вызовов DeepSeek).

    Returns:
        Обновлённый case_context с заполненным summary.
    """
    documents = case_context.get("documents", [])
    if not documents:
        case_context["summary"] = {}
        return case_context

    # Собираем все extracted данные в один текстовый блок
    import json
    all_extractions = []
    for doc in documents:
        ext = doc.get("extracted", {})
        if ext:
            all_extractions.append({
                "filename": doc.get("filename", "unknown"),
                "doc_type": doc.get("doc_type", "other"),
                "extracted": ext,
            })

    if not all_extractions:
        case_context["summary"] = {}
        return case_context

    extractions_json = json.dumps(all_extractions, ensure_ascii=False, indent=1)

    # Обрезаем если слишком длинный (защита от переполнения контекста)
    max_chars = 80_000  # ~25K токенов
    if len(extractions_json) > max_chars:
        extractions_json = extractions_json[:max_chars] + "\n... [обрезано]"

    messages = [
        {"role": "system", "content": build_summary_update_messages.__doc__ or
         "Ты — помощник судьи. Составь сводку дела из обработанных документов. Верни СТРОГО JSON."},
        {"role": "user", "content": f"""\
Составь полную сводку судебного дела на основании ВСЕХ обработанных документов ({len(all_extractions)} шт).

ОБРАБОТАННЫЕ ДОКУМЕНТЫ:
{extractions_json}

Верни JSON строго по схеме:
{{
  "parties": {{
    "plaintiff": {{"name": "...", "type": "individual/legal_entity", "inn": null, "ogrn": null, "address": "...", "representative": "..."}},
    "defendant": {{"name": "...", "type": "individual/legal_entity", "inn": null, "ogrn": null, "address": "...", "representative": "..."}},
    "third_parties": [],
    "prosecutor_or_authority": null
  }},
  "claims": [
    {{"type": "principal/penalty/moral_damage/legal_costs/other", "amount": 0, "description": "..."}}
  ],
  "arguments_plaintiff": ["довод 1", "довод 2"],
  "arguments_defendant": ["довод 1", "довод 2"],
  "admissions": [
    {{"party": "plaintiff/defendant", "fact": "что признано"}}
  ],
  "key_evidence": [
    {{"doc": "название документа", "proves": "что доказывает"}}
  ],
  "legal_norms": ["ст. 309 ГК РФ", "ст. 310 ГК РФ"],
  "timeline": [
    {{"date": "YYYY-MM-DD", "event": "что произошло"}}
  ],
  "contradictions": ["описание противоречия"],
  "missing_documents": ["документ упоминается, но не загружен"]
}}"""},
    ]

    try:
        result = await deepseek.chat(messages, max_tokens=4096, temperature=0.1)
        new_summary = _parse_json_response(result["content"])
        if new_summary:
            case_context["summary"] = new_summary
            logger.info(f"Summary скомпилирован из {len(all_extractions)} документов")
        else:
            logger.warning("Не удалось распарсить скомпилированный summary")
    except Exception as e:
        logger.error(f"Ошибка компиляции summary: {e}")

    return case_context


async def remove_document(case_context: dict, doc_index: int) -> dict:
    """
    Удаляет документ из case_context по индексу и пересчитывает summary.

    Args:
        case_context: текущий контекст
        doc_index: индекс документа для удаления

    Returns:
        Обновлённый case_context

    Raises:
        ValueError: если индекс невалидный
    """
    documents = case_context.get("documents", [])

    # Ищем документ по doc_index
    target_idx = None
    for i, doc in enumerate(documents):
        if doc.get("doc_index") == doc_index:
            target_idx = i
            break

    if target_idx is None:
        raise ValueError(f"Документ с индексом {doc_index} не найден")

    removed = documents.pop(target_idx)
    logger.info(f"Удалён документ: {removed.get('filename')} (index={doc_index})")

    # Пересчитываем индексы
    for i, doc in enumerate(documents):
        doc["doc_index"] = i
    case_context["doc_count"] = len(documents)
    case_context["total_chars"] = sum(
        d.get("ocr_chars", 0) for d in documents
    )

    # Пересчитываем summary из оставшихся документов
    if documents:
        await _rebuild_summary(case_context)
    else:
        case_context["summary"] = {}

    return case_context


async def _rebuild_summary(case_context: dict) -> None:
    """
    Пересчитывает summary с нуля из всех оставшихся extracted-документов.
    Используется при удалении документа.
    """
    documents = case_context.get("documents", [])
    if not documents:
        case_context["summary"] = {}
        return

    # Проходим по документам и последовательно строим summary
    current_summary = {}
    for doc in documents:
        extracted = doc.get("extracted", {})
        doc_type = doc.get("doc_type", "other")
        filename = doc.get("filename", "unknown")

        try:
            messages = build_summary_update_messages(
                current_summary=current_summary,
                extracted_data=extracted,
                doc_type=doc_type,
                filename=filename,
            )
            result = await deepseek.chat(messages, max_tokens=4096, temperature=0.1)
            new_summary = _parse_json_response(result["content"])
            if new_summary:
                current_summary = new_summary
        except Exception as e:
            logger.error(f"Ошибка пересчёта summary для {filename}: {e}")
            continue

    case_context["summary"] = current_summary


def _repair_json(text: str) -> str:
    """Попытка починить типичные ошибки JSON от LLM."""
    # Убираем trailing commas перед } или ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # Убираем комментарии // ...
    text = re.sub(r'//[^\n]*', '', text)
    return text


def _parse_json_response(text: str) -> dict | None:
    """
    Парсит JSON из ответа DeepSeek. Обрабатывает случаи, когда
    модель оборачивает JSON в ```json ... ``` или добавляет текст.
    С автоматическим repair при ошибках.
    """
    if not text:
        return None
    text = text.strip()

    # Убираем markdown code block
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3].strip()

    # Попробуем напрямую
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Попробуем repair + напрямую
    repaired = _repair_json(text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Попробуем найти JSON-объект в тексте
    brace_start = text.find("{")
    if brace_start == -1:
        return None

    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[brace_start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    try:
                        return json.loads(_repair_json(candidate))
                    except json.JSONDecodeError:
                        pass
                break

    # Последняя попытка: обрезанный ответ — дополним скобками
    brace_start = text.find("{")
    if brace_start != -1:
        fragment = _repair_json(text[brace_start:])
        open_braces = fragment.count("{") - fragment.count("}")
        open_brackets = fragment.count("[") - fragment.count("]")
        if open_braces > 0 or open_brackets > 0:
            if fragment.count('"') % 2 != 0:
                fragment += '"'
            fragment += "]" * open_brackets + "}" * open_braces
            try:
                return json.loads(fragment)
            except json.JSONDecodeError:
                pass

    return None
