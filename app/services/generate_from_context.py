"""
Модуль 3: Generate — генерация решения из накопленного контекста.

Вход: case_context.summary (не сырые тексты, а извлечённая и сведённая информация).
Выход: SSE-стрим текста решения через существующий Redis.

Паттерн идентичен pipeline.py → run_pipeline_streaming(),
но вместо raw текста используется summary.
"""

import asyncio
import json
import re
import time
import logging

from app.services.deepseek import deepseek
from app.services.redis_stream import publish_chunk, publish_event, set_stream_status
from app.models import Case

logger = logging.getLogger(__name__)


# ── Фоновая валидация норм (AI-ревизор) ────────────────────────

async def _validate_norms_background(case_id: str, text: str):
    """Фоновая проверка юридических ссылок — запускается ПОСЛЕ генерации.

    1. Regex: извлечь все ссылки из текста
    2. БД: найти каждую ссылку в legal_norms
    3. AI-ревизор: проверить + исправить некорректные
    4. Сохранить: validation_result + исправленный final_text
    5. SSE: уведомить фронтенд
    """
    from app.database import async_session
    from app.services.reference_extractor import extract_legal_references
    from app.services.norm_lookup import lookup_references
    from app.services.norm_reviewer import review_norms, build_validation_result

    logger.info("Norm validation started for case %s", case_id)
    t0 = time.time()

    try:
        async with async_session() as db:
            # Шаг 1: Извлечь ссылки (regex)
            refs = extract_legal_references(text)
            if not refs:
                logger.info("Norm validation: no references found in case %s", case_id)
                return

            logger.info("Norm validation: found %d references in case %s", len(refs), case_id)

            # Шаг 2: Поиск в БД
            refs_with_lookup = await lookup_references(refs, db)
            found_count = sum(1 for r in refs_with_lookup if r.get("db_status") == "found")
            logger.info(
                "Norm validation: %d/%d found in DB for case %s",
                found_count, len(refs_with_lookup), case_id,
            )

            # Шаг 3: AI-ревизор
            review_result = await review_norms(text, refs_with_lookup)

            # Шаг 4: Определяем финальный текст
            corrected_text = review_result["corrected_text"]
            text_changed = corrected_text != text

            # Шаг 4b: Если текст изменился — пересчитываем позиции ссылок
            if text_changed:
                # Пересчитываем позиции ссылок на corrected_text
                new_refs = extract_legal_references(corrected_text)
                # Маппим старые ссылки к новым по raw тексту
                _update_positions(refs_with_lookup, new_refs)

            # Шаг 5: Формируем validation_result (с правильными позициями)
            validation_result = build_validation_result(
                refs_with_lookup,
                review_result["corrections"],
                review_result["stats"],
            )

            # Шаг 6: Сохранить в БД
            from sqlalchemy import select
            from app.models import Case as CaseModel
            case = (await db.execute(
                select(CaseModel).where(CaseModel.id == case_id)
            )).scalar_one_or_none()

            if case:
                # Обновляем final_text если были исправления
                if text_changed:
                    case.final_text = corrected_text
                case.validation_result = validation_result
                await db.commit()

                logger.info(
                    "Norm validation done for case %s in %.1fs: "
                    "%d refs, %d confirmed, %d fixed, %d removed",
                    case_id, time.time() - t0,
                    review_result["stats"]["total_refs"],
                    review_result["stats"]["confirmed"],
                    review_result["stats"]["fixed"],
                    review_result["stats"]["removed"],
                )

                # Шаг 6: SSE уведомление
                try:
                    await publish_event(
                        case_id,
                        {
                            "type": "validation_complete",
                            "stats": review_result["stats"],
                        },
                    )
                except Exception as e:
                    logger.warning("Failed to send validation SSE for case %s: %s", case_id, e)
            else:
                logger.warning("Case %s not found for validation update", case_id)

    except Exception as e:
        logger.error("Norm validation failed for case %s: %s", case_id, e, exc_info=True)
        # Не ломаем основной flow — валидация опциональна


def _update_positions(old_refs: list[dict], new_refs: list[dict]):
    """Обновляет position/end_position в old_refs по данным из new_refs.

    Маппинг по raw тексту: если ссылка "ст. 56 ГПК РФ" была на позиции 1234
    в оригинале, а в исправленном тексте на позиции 1200 — обновляем.

    Для fix_sentence/fix_ref ссылок raw текст мог измениться —
    матчим по типу + ближайшей позиции и обновляем raw.
    """
    # Строим индекс: raw -> список позиций (может быть несколько одинаковых ссылок)
    new_by_raw: dict[str, list[dict]] = {}
    new_by_type: dict[str, list[dict]] = {}
    for nr in new_refs:
        raw = nr.get("raw", "")
        new_by_raw.setdefault(raw, []).append(nr)
        rtype = nr.get("type", "")
        new_by_type.setdefault(rtype, []).append(nr)

    used: set[int] = set()  # id() новых ссылок, уже использованных

    for old_ref in old_refs:
        raw = old_ref.get("raw", "")
        # Попытка 1: точное совпадение по raw
        candidates = new_by_raw.get(raw, [])
        best = _find_closest(candidates, old_ref, used)

        # Попытка 2: если не нашли (fix_sentence изменил raw) — ищем по типу + позиции
        if best is None:
            rtype = old_ref.get("type", "")
            type_candidates = new_by_type.get(rtype, [])
            best = _find_closest(type_candidates, old_ref, used, max_dist=500)

        if best is not None:
            old_ref["position"] = best["position"]
            old_ref["end_position"] = best["end_position"]
            old_ref["raw"] = best.get("raw", old_ref["raw"])  # обновляем raw
            used.add(id(best))


def _find_closest(candidates, old_ref, used, max_dist=float("inf")):
    """Найти ближайшую неиспользованную ссылку по позиции."""
    best = None
    best_dist = float("inf")
    for c in candidates:
        if id(c) in used:
            continue
        dist = abs(c.get("position", 0) - old_ref.get("position", 0))
        if dist < best_dist and dist <= max_dist:
            best = c
            best_dist = dist
    return best


# ── Промпт генерации решения ────────────────────────────────────

GENERATE_SYSTEM = """\
Следуй инструкции пользователя. Составь юридический документ согласно заданию.
Используй только факты из предоставленных материалов дела.
Ссылайся на нормы права Российской Федерации.
При ссылке на норму ОБЯЗАТЕЛЬНО подробно раскрывай её содержание в тексте.
Формат вывода: чистый текст, без разметки (без **, без #, без markdown)."""


# ── Категорийные дополнения ──────────────────────────────────────

CATEGORY_ADDITIONS: dict[str, str] = {
    "consumer": """\
ПОТРЕБИТЕЛЬСКИЙ СПОР — ДОПОЛНИТЕЛЬНО ПРОВЕРЬ:
- Штраф 50% от присуждённой суммы (п. 6 ст. 13 ЗоЗПП) — взыскивается СУДОМ, даже если истец не заявлял
- Моральный вред — презюмируется при нарушении прав потребителя (ст. 15 ЗоЗПП)
- Неустойка: 1%/день (товар, ст. 23 ЗоЗПП) / 3%/день (услуга, ст. 28 ЗоЗПП)
- Бремя доказывания: на продавце/исполнителе
- Госпошлина: потребитель освобождён до 1 000 000 руб.""",

    "labor": """\
ТРУДОВОЙ СПОР — ДОПОЛНИТЕЛЬНО ПРОВЕРЬ:
- Бремя доказывания законности увольнения — на РАБОТОДАТЕЛЕ
- Процедура увольнения: каждый шаг (уведомление, объяснительная, сроки, приказ)
- Восстановление на работе: немедленное исполнение (ст. 211 ГПК)
- Средний заработок за вынужденный прогул
- Моральный вред: обязателен при ЛЮБОМ нарушении трудовых прав (ст. 237 ТК)
- Компенсация за неиспользованный отпуск
- Срок обращения: 1 месяц (увольнение), 1 год (зарплата) — ст. 392 ТК""",

    "family": """\
СЕМЕЙНЫЙ СПОР — ДОПОЛНИТЕЛЬНО ПРОВЕРЬ:
- Интересы ребёнка — ПРИОРИТЕТ №1 (ст. 65 СК)
- Заключение органа опеки (ст. 78 СК) — без него решение отменят
- Мнение ребёнка старше 10 лет (ст. 57 СК)
- Алименты: 1/4 на одного, 1/3 на двоих, 1/2 на трёх+ (ст. 81 СК)
- Немедленное исполнение: алименты (ст. 211 ГПК)
- Раздел имущества: равные доли по умолчанию (ст. 39 СК)""",

    "inheritance": """\
НАСЛЕДСТВЕННЫЙ СПОР — ДОПОЛНИТЕЛЬНО ПРОВЕРЬ:
- Круг наследников, очерёдность (ст. 1142–1145 ГК)
- Обязательная доля (ст. 1149 ГК): не менее 1/2 законной доли
- Способ принятия: нотариальное или фактическое
- Срок: 6 месяцев (ст. 1154 ГК)
- Долги наследодателя: в пределах стоимости наследства""",

    "traffic": """\
ДТП / СТРАХОВАНИЕ — ДОПОЛНИТЕЛЬНО ПРОВЕРЬ:
- ОСАГО лимиты: 400 000 (имущество), 500 000 (жизнь/здоровье)
- Износ: с учётом износа (ОСАГО) vs без износа (к виновнику)
- УТС: взыскивается с виновника
- Источник повышенной опасности (ст. 1079 ГК): ответственность БЕЗ вины
- Суброгация (ст. 965 ГК)""",

    "housing": """\
ЖКХ — ДОПОЛНИТЕЛЬНО ПРОВЕРЬ:
- Тарифы: утверждены муниципалитетом?
- ПП РФ №354 (правила предоставления коммунальных услуг)
- Акт осмотра / акт о заливе: кем составлен, когда
- Кворум общего собрания собственников
- Срок оспаривания решений ОСС: 6 месяцев (ст. 46 ЖК)""",
}


def _detect_category(summary: dict) -> str | None:
    """
    Эвристика: определяет категорию дела по содержимому summary.
    Возвращает ключ из CATEGORY_ADDITIONS или None.
    """
    if not summary:
        return None

    # Собираем весь текст для поиска ключевых слов
    text_parts = []
    for claim in summary.get("claims", []):
        text_parts.append(claim.get("description", ""))
    for norm in summary.get("legal_norms", []):
        text_parts.append(norm)
    for arg in summary.get("arguments_plaintiff", []):
        text_parts.append(arg)
    for arg in summary.get("arguments_defendant", []):
        text_parts.append(arg)
    text = " ".join(text_parts).lower()

    # Потребительские
    consumer_keywords = ["зозпп", "защит прав потребител", "потребител", "ст. 13 зозпп",
                         "ст. 18 зозпп", "ст. 23 зозпп", "ст. 28 зозпп"]
    if any(kw in text for kw in consumer_keywords):
        return "consumer"

    # Трудовые
    labor_keywords = ["трудов", "увольнен", "работодател", "заработн", "ст. 392 тк",
                      "ст. 77 тк", "ст. 80 тк", "ст. 81 тк", "ст. 237 тк"]
    if any(kw in text for kw in labor_keywords):
        return "labor"

    # Семейные
    family_keywords = ["алимент", "расторжен брак", "развод", "опек", "ст. 81 ск",
                       "ст. 80 ск", "раздел имущества супруг"]
    if any(kw in text for kw in family_keywords):
        return "family"

    # Наследственные
    inheritance_keywords = ["наследств", "наследодат", "завещан", "ст. 1142",
                            "ст. 1149", "обязательн дол"]
    if any(kw in text for kw in inheritance_keywords):
        return "inheritance"

    # ДТП
    traffic_keywords = ["дтп", "осаго", "каско", "страхов возмещ", "ст. 1079",
                        "ст. 965", "ст. 12 закон об осаго"]
    if any(kw in text for kw in traffic_keywords):
        return "traffic"

    # ЖКХ
    housing_keywords = ["жкх", "коммунальн", "управляющ компан", "тсж",
                        "общедомов", "ст. 46 жк", "ст. 161 жк", "пп рф №354"]
    if any(kw in text for kw in housing_keywords):
        return "housing"

    return None


def _build_generate_prompt(case: Case) -> list[dict]:
    """
    Формирует messages для генерации решения из case_context.

    Returns:
        list[dict] — messages для deepseek.chat_stream()
    """
    ctx = case.case_context or {}
    summary = ctx.get("summary", {})
    # Text-only cases store summary as plain string
    if isinstance(summary, str):
        summary = {"description": summary, "claims": [], "legal_norms": [], "arguments_plaintiff": [], "arguments_defendant": []}
    doc_count = ctx.get("doc_count", 0)

    summary_json = json.dumps(summary, ensure_ascii=False, indent=2)

    # Инструкции пользователя
    instructions_block = ""
    if case.user_instructions and case.user_instructions.strip():
        instructions_block = (
            f"\n\nИНСТРУКЦИЯ:\n"
            f"{case.user_instructions.strip()}\n"
        )

    # Категорийное дополнение
    category = _detect_category(summary)
    category_block = ""
    if category and category in CATEGORY_ADDITIONS:
        category_block = f"\n\n{CATEGORY_ADDITIONS[category]}\n"
        logger.info(f"Категория дела: {category}")

    user_content = (
        f"МАТЕРИАЛЫ ДЕЛА (сводка из {doc_count} документов):\n\n"
        f"{summary_json}"
        f"{instructions_block}"
        f"{category_block}\n\n"
        f"Выполни инструкцию. Используй материалы дела."
    )

    return [
        {"role": "system", "content": GENERATE_SYSTEM},
        {"role": "user", "content": user_content},
    ]


async def generate_from_context(
    case_id: str,
    case: Case,
    db,
) -> dict:
    t0 = time.time()
    ctx = case.case_context or {}
    doc_count = ctx.get("doc_count", 0)
    summary = ctx.get("summary", {})
    if isinstance(summary, str):
        summary = {"description": summary, "claims": [], "legal_norms": [], "arguments_plaintiff": [], "arguments_defendant": []}
    logger.info(f"Generate from context: case={case_id}, docs={doc_count}")
    if not summary:
        raise ValueError("case_context.summary is empty")
    messages = _build_generate_prompt(case)
    prompt_chars = sum(len(m["content"]) for m in messages)
    est_prompt_tokens = prompt_chars // 3
    logger.info(f"Prompt: {prompt_chars} chars (~{est_prompt_tokens} tokens)")

    # --- Retry with exponential backoff (10s, 30s, 90s) ---
    max_retries = 3
    backoff_delays = [10, 30, 90]
    full_text = ""

    for attempt in range(max_retries):
        try:
            full_text_parts = []
            async for chunk in deepseek.chat_stream(messages, max_tokens=8192, temperature=0.3):
                full_text_parts.append(chunk)
                await publish_chunk(case_id, chunk)
            full_text = "".join(full_text_parts)
            if len(full_text.strip()) < 100:
                raise ValueError(f"DeepSeek returned too little text: {len(full_text)} chars")
            logger.info(f"DeepSeek stream OK on attempt {attempt + 1}: {len(full_text)} chars")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                delay = backoff_delays[attempt]
                logger.warning(f"DeepSeek attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {delay}s...")
                await set_stream_status(case_id, "retrying")
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(f"DeepSeek failed after {max_retries} attempts: {e}")
                await set_stream_status(case_id, "error")
                raise RuntimeError("Сервер ИИ временно недоступен, решение будет готово в течение 30 минут") from e
    else:
        raise RuntimeError("DeepSeek generation failed after all retries")

    # Clean markdown
    full_text = re.sub(r"\*\*(.+?)\*\*", r"\1", full_text)
    full_text = re.sub(r"__(.+?)__", r"\1", full_text)
    full_text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", full_text)
    full_text = re.sub(r"^#{1,6}\s+", "", full_text, flags=re.MULTILINE)

    t_ai = time.time()
    logger.info(f"DeepSeek stream: {len(full_text)} chars in {t_ai - t0:.1f}s")

    case.generated_text = full_text
    case.final_text = full_text
    case.matched_norms = None
    case.validation_result = None
    case.fact_pack = {"source": "accumulator_pipeline", "doc_count": doc_count}
    case.status = "completed"

    if not case.title:
        from app.services.pipeline import _auto_title_from_instructions, _auto_title_from_text
        # Сначала пробуем извлечь из user_instructions
        auto = _auto_title_from_instructions(case.user_instructions or "")
        # Fallback: первые 80 символов сгенерированного текста
        if not auto:
            auto = _auto_title_from_text(full_text)
        if auto:
            case.title = auto
            logger.info(f"Auto-title: {case.title}")

    est_completion_tokens = len(full_text) // 3
    total = {"prompt_tokens": est_prompt_tokens, "completion_tokens": est_completion_tokens}
    case.tokens_used = total
    total_tokens = est_prompt_tokens + est_completion_tokens

    from app.config import get_settings
    _s = get_settings()
    # Cost = DeepSeek tokens + OCR pages. OCR was previously excluded, which
    # made admin revenue analytics show only ~0.2 RUB/case.
    _ds_cost_rub = est_prompt_tokens * _s.ds_cost_per_input_token + est_completion_tokens * _s.ds_cost_per_output_token
    # OCR cost = реальные ocr_chars × rate (калибровано под Yandex Vision bill).
    # Раньше считали file_count × est_pages_per_pdf × rate — сильно завышало.
    try:
        _total_ocr_chars = 0
        for _doc in (case.case_context or {}).get('documents', []):
            _total_ocr_chars += int(_doc.get('ocr_chars', 0) or 0)
        _ocr_cost_rub = _total_ocr_chars * 0.00018  # ~0.18 RUB/1000 chars
    except Exception:
        _ocr_cost_rub = 0.0
    cost_rub = _ds_cost_rub + _ocr_cost_rub
    case.cost_kopecks = round(cost_rub * 100)

    await set_stream_status(case_id, "completed")

    logger.info(
        f"Generate done in {time.time() - t0:.1f}s, "
        f"{len(full_text)} chars, ~{total_tokens} tokens, "
        f"docs={doc_count}"
    )

    asyncio.create_task(_validate_norms_background(case_id, full_text))

    return {"total_tokens": total_tokens, "usage": total}
