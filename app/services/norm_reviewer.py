"""
AI-ревизор юридических ссылок.

Второй AI-проход: получает текст + результаты проверки в БД →
проверяет корректность ссылок → исправляет некорректные.

Flow:
  1. reference_extractor → извлекает ссылки из текста (regex)
  2. norm_lookup → ищет каждую ссылку в БД legal_norms
  3. norm_reviewer (этот файл) → AI проверяет и исправляет
  4. apply_corrections → заменяет текст

Промпт для ревизора:
  - Для ссылок "found" — проверить что норма используется в правильном контексте
  - Для ссылок "not_found" — определить: реальная, галлюцинация, или полностью вымышленная
  - Формат ответа: JSON с corrections[]
"""

import json
import logging
from typing import Optional

from app.services.deepseek import deepseek
from app.services.reference_extractor import get_sentence_around_ref

logger = logging.getLogger(__name__)


REVIEWER_SYSTEM_PROMPT = """Ты — юридический ревизор, специалист по нормативным актам Российской Федерации.

ЗАДАЧА: Проверь каждую ссылку на нормы права в тексте судебного решения.
Для каждой ссылки у тебя есть результат поиска в нашей базе данных (найдено / не найдено).

ИНСТРУКЦИИ:

1. Для ссылок со статусом "found" (найдено в БД):
   - ВСЕГДА действие "confirm". НЕ МЕНЯЙ ссылки, найденные в БД.
   - Даже если контекст кажется неидеальным — норма реальна и верифицирована.
   - Никогда не применяй "fix_ref", "fix_sentence" или "remove" к найденным нормам.

2. Для ссылок со статусом "not_found" (не найдено в БД):
   Определи одно из трёх:
   a) Реальная норма, просто отсутствует в нашей БД → "confirm" с пометкой
   b) Ссылка с ошибкой (неправильный номер/дата/пункт) → "fix_ref" с правильной ссылкой
   c) Норма полностью вымышлена (галлюцинация AI) → "remove"

3. КРИТИЧЕСКИ ВАЖНО: НЕ удаляй ссылки на реальные нормы только потому что их нет в БД.
   БД может быть неполной. Если ты УВЕРЕН что норма реальна — "confirm".

4. НЕ добавляй новые ссылки на нормы. НЕ меняй текст за пределами предложений с ошибками.

ФОРМАТ ОТВЕТА — строго JSON:
{
  "corrections": [
    {
      "ref_index": 0,
      "ref_raw": "ст. 395 ГК РФ",
      "action": "confirm",
      "reason": "Норма корректна, используется в правильном контексте"
    },
    {
      "ref_index": 2,
      "ref_raw": "ППВС от 28.06.2012 №18",
      "action": "fix_ref",
      "original_text": "Согласно ППВС от 28.06.2012 №18",
      "corrected_text": "Согласно ППВС от 28.06.2012 №17",
      "reason": "Постановление №18 не существует. По дате 28.06.2012 выпущено Постановление №17 о защите прав потребителей."
    },
    {
      "ref_index": 5,
      "ref_raw": "Определение ВС РФ от 15.03.2024 № 305-ЭС24-9999",
      "action": "remove",
      "original_text": "как указано в Определении ВС РФ от 15.03.2024 № 305-ЭС24-9999,",
      "corrected_text": "",
      "reason": "Определение с таким номером не существует. Вероятная галлюцинация AI."
    }
  ]
}

Действия (action):
- confirm  — ссылка и контекст верны, ничего не менять
- fix_ref  — заменить только ссылку (неправильный номер/дата), контекст предложения верный
- fix_sentence — переписать всё предложение (содержание не соответствует норме)
- remove   — удалить упоминание этой ссылки (норма вымышлена и замены нет)

Отвечай ТОЛЬКО валидным JSON. Без пояснений до/после JSON."""


def _build_reviewer_prompt(
    generated_text: str,
    refs_with_lookup: list[dict],
) -> str:
    """Построить промпт для ревизора с текстом и ссылками."""
    parts = []
    parts.append("ТЕКСТ СУДЕБНОГО РЕШЕНИЯ:")
    parts.append("---")
    # Ограничиваем длину текста чтобы не превысить контекст
    parts.append(generated_text[:12000])
    parts.append("---\n")

    parts.append(f"ССЫЛКИ НА НОРМЫ ({len(refs_with_lookup)} шт.):\n")

    for i, ref in enumerate(refs_with_lookup):
        # Получаем предложение вокруг ссылки
        sentence = get_sentence_around_ref(
            generated_text,
            ref.get("position", 0),
            ref.get("end_position", 0),
        )

        parts.append(f"[{i}] \"{ref.get('raw', '')}\"")
        parts.append(f"    Тип: {ref.get('type', 'unknown')}")
        parts.append(f"    Статус в БД: {ref.get('db_status', 'unknown')}")

        if ref.get("db_status") == "found":
            doc_title = ref.get("doc_title", "")
            norm_text = ref.get("norm_text", "")
            is_active = ref.get("is_active", True)
            if doc_title:
                parts.append(f"    Документ: {doc_title[:100]}")
            if norm_text:
                parts.append(f"    Текст нормы: {norm_text[:500]}")
            if not is_active:
                inactive_reason = ref.get("inactive_reason", "")
                parts.append(f"    ⚠️ НОРМА УТРАТИЛА СИЛУ! {inactive_reason or ''}")
                parts.append("    → Нужно заменить на действующую норму или удалить ссылку.")
        else:
            parts.append("    ⚠️ НЕ НАЙДЕНО в базе данных — возможная галлюцинация!")

        if sentence:
            parts.append(f"    Контекст: \"{sentence[:300]}\"")
        parts.append("")

    return "\n".join(parts)


async def review_norms(
    generated_text: str,
    refs_with_lookup: list[dict],
) -> dict:
    """
    AI-ревизор проверяет корректность ссылок на нормы.

    Args:
        generated_text: Сгенерированный текст судебного решения
        refs_with_lookup: Ссылки, обогащённые результатами поиска в БД
            (из norm_lookup.lookup_references())

    Returns: {
        "corrected_text": str,        # текст с исправленными нормами
        "corrections": [dict],         # список исправлений
        "stats": {                     # статистика
            "total_refs": int,
            "confirmed": int,
            "fixed": int,
            "removed": int,
            "error": int,
        }
    }
    """
    if not refs_with_lookup:
        return {
            "corrected_text": generated_text,
            "corrections": [],
            "stats": {
                "total_refs": 0, "confirmed": 0,
                "fixed": 0, "removed": 0, "error": 0,
            },
        }

    # Строим промпт
    user_prompt = _build_reviewer_prompt(generated_text, refs_with_lookup)

    logger.info(
        "Norm reviewer: checking %d references (%d found, %d not_found)",
        len(refs_with_lookup),
        sum(1 for r in refs_with_lookup if r.get("db_status") == "found"),
        sum(1 for r in refs_with_lookup if r.get("db_status") == "not_found"),
    )

    # Вызываем AI
    try:
        result = await deepseek.chat(
            messages=[
                {"role": "system", "content": REVIEWER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=4096,
            temperature=0.1,  # минимальная креативность для проверки
        )
        response_text = result.get("content", "")
        logger.info(
            "Norm reviewer: got response (%d chars, %d tokens)",
            len(response_text),
            result.get("usage", {}).get("total_tokens", 0),
        )
    except Exception as e:
        logger.error("Norm reviewer AI call failed: %s", e)
        # Если AI недоступен — возвращаем текст без изменений
        return {
            "corrected_text": generated_text,
            "corrections": [],
            "stats": {
                "total_refs": len(refs_with_lookup),
                "confirmed": 0, "fixed": 0, "removed": 0,
                "error": len(refs_with_lookup),
            },
        }

    # Парсим JSON ответ
    corrections = _parse_reviewer_response(response_text)

    # Guard: found norms must always be confirmed, never modified
    for corr in corrections:
        ref_idx = corr.get("ref_index")
        action = corr.get("action", "")
        if ref_idx is not None and ref_idx < len(refs_with_lookup):
            ref = refs_with_lookup[ref_idx]
            if ref.get("db_status") == "found" and action != "confirm":
                logger.warning(
                    "Norm reviewer: blocked %s on found norm '%s', forcing confirm",
                    action, corr.get("ref_raw", "")[:50],
                )
                corr["action"] = "confirm"
                corr["reason"] = f"[auto-confirm] Норма найдена в БД (original: {action})"

    # Применяем исправления
    corrected_text = apply_corrections(generated_text, corrections)

    # Считаем статистику
    stats = {
        "total_refs": len(refs_with_lookup),
        "confirmed": sum(1 for c in corrections if c.get("action") == "confirm"),
        "fixed": sum(1 for c in corrections if c.get("action") in ("fix_ref", "fix_sentence")),
        "removed": sum(1 for c in corrections if c.get("action") == "remove"),
        "error": 0,
    }
    stats["error"] = stats["total_refs"] - stats["confirmed"] - stats["fixed"] - stats["removed"]

    logger.info(
        "Norm reviewer: %d confirmed, %d fixed, %d removed, %d error",
        stats["confirmed"], stats["fixed"], stats["removed"], stats["error"],
    )

    return {
        "corrected_text": corrected_text,
        "corrections": corrections,
        "stats": stats,
    }


def _parse_reviewer_response(response_text: str) -> list[dict]:
    """Парсит JSON ответ от AI-ревизора.

    Устойчив к мусору вокруг JSON (markdown блоки, пояснения).
    """
    # Пытаемся найти JSON в ответе
    text = response_text.strip()

    # Убираем markdown code block если есть
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]  # убираем первую строку ```json
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    # Ищем JSON объект
    json_start = text.find("{")
    json_end = text.rfind("}") + 1

    if json_start == -1 or json_end == 0:
        logger.warning("Norm reviewer: no JSON found in response")
        return []

    json_str = text[json_start:json_end]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("Norm reviewer: invalid JSON: %s", e)
        # Пробуем починить типичные проблемы
        try:
            # Иногда AI добавляет trailing comma
            fixed = json_str.replace(",]", "]").replace(",}", "}")
            data = json.loads(fixed)
        except json.JSONDecodeError:
            logger.error("Norm reviewer: cannot parse JSON response")
            return []

    corrections = data.get("corrections", [])

    # Валидация каждого correction
    valid = []
    for corr in corrections:
        action = corr.get("action", "")
        if action not in ("confirm", "fix_ref", "fix_sentence", "remove"):
            logger.warning("Norm reviewer: unknown action '%s', skipping", action)
            continue
        valid.append(corr)

    return valid


def apply_corrections(text: str, corrections: list[dict]) -> str:
    """Применяет исправления к тексту.

    Обрабатывает только action=fix_ref, fix_sentence, remove.
    Для confirm ничего не делает.
    """
    for corr in corrections:
        action = corr.get("action", "")

        if action == "confirm":
            continue

        original = corr.get("original_text", "")
        corrected = corr.get("corrected_text", "")

        if not original:
            continue

        if action in ("fix_ref", "fix_sentence"):
            if corrected:
                text = text.replace(original, corrected, 1)
            else:
                logger.warning(
                    "Norm reviewer: fix without corrected_text for '%s'",
                    original[:50],
                )

        elif action == "remove":
            # Удаляем текст, очищаем двойные пробелы/точки
            text = text.replace(original, "", 1)
            # Убираем двойные пробелы
            while "  " in text:
                text = text.replace("  ", " ")
            # Убираем двойные точки
            text = text.replace("..", ".")

    return text.strip()


def build_validation_result(
    refs_with_lookup: list[dict],
    corrections: list[dict],
    stats: dict,
) -> dict:
    """Формирует validation_result для сохранения в case.validation_result (JSONB).

    Используется фронтендом для отображения бейджей и inline-подсветки.
    """
    # Маппим corrections по ref_index
    corrections_by_index = {}
    for corr in corrections:
        idx = corr.get("ref_index")
        if idx is not None:
            corrections_by_index[idx] = corr

    references = []
    for i, ref in enumerate(refs_with_lookup):
        corr = corrections_by_index.get(i)
        action = corr.get("action", "unknown") if corr else "unknown"

        # Определяем статус для бейджа
        # Приоритет: outdated > fix/remove > verified > unverified
        is_active = ref.get("is_active", True)

        if not is_active and action != "remove":
            status = "outdated"  # ⚠️ Норма утратила силу
        elif action in ("fix_ref", "fix_sentence"):
            status = "fixed"  # 🔧 Исправлено AI-ревизором
        elif action == "remove":
            status = "removed"  # ❌ Удалено (галлюцинация)
        elif ref.get("db_status") == "found" and action == "confirm":
            status = "verified"  # ✅ Проверено
        elif action == "confirm" and ref.get("db_status") == "not_found":
            status = "unverified"  # Не в БД, но AI считает реальной
        else:
            status = "unknown"

        entry = {
            "raw": ref.get("raw", ""),
            "type": ref.get("type", ""),
            "position": ref.get("position", 0),
            "end_position": ref.get("end_position", 0),
            "db_status": ref.get("db_status", "not_found"),
            "status": status,
            "norm_id": ref.get("norm_id"),
            "doc_title": ref.get("doc_title"),
            "is_active": is_active,
            "inactive_reason": ref.get("inactive_reason") if not is_active else None,
        }

        if corr and action != "confirm":
            entry["correction"] = {
                "action": action,
                "original_text": corr.get("original_text", ""),
                "corrected_text": corr.get("corrected_text", ""),
                "reason": corr.get("reason", ""),
            }

        references.append(entry)

    return {
        "references": references,
        "stats": stats,
        "version": 1,
    }
