"""Система самообучения.

Модули:
1. diff_tracker — сравнение generated_text и final_text
2. pattern_analyzer — выявление частых правок
3. exemplar_manager — отбор эталонных генераций
4. style_profiler — профиль стиля судьи
5. norm_crowdsourcer — учёт добавленных судьями норм
6. hallucination_detector — логирование удалённых ссылок
7. nightly_job — ночной cron, объединяет всё

Запуск: python -m app.services.learning
"""
import re
import asyncio
import logging
from difflib import SequenceMatcher
from collections import Counter
from datetime import datetime, timezone
from uuid import UUID as PyUUID

from sqlalchemy import select, func, text, or_ as db_or
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Case, User, Exemplar, NormAssociation, HallucinationLog, LegalNorm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── 1. Diff-трекер ──

def compute_edit_distance(a: str, b: str) -> int:
    """Простой edit distance через SequenceMatcher (по словам)."""
    words_a = a.split()
    words_b = b.split()
    matcher = SequenceMatcher(None, words_a, words_b)
    # Кол-во изменённых слов
    changes = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            changes += max(i2 - i1, j2 - j1)
    return changes


def get_diff_details(generated: str, final: str) -> dict:
    """Детальный diff: что добавлено, удалено, изменено."""
    gen_lines = generated.splitlines()
    fin_lines = final.splitlines()
    matcher = SequenceMatcher(None, gen_lines, fin_lines)

    added = []
    removed = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added.extend(fin_lines[j1:j2])
        elif tag == "delete":
            removed.extend(gen_lines[i1:i2])
        elif tag == "replace":
            removed.extend(gen_lines[i1:i2])
            added.extend(fin_lines[j1:j2])

    return {"added": added, "removed": removed, "edit_distance": compute_edit_distance(generated, final)}


# ── 2. Анализатор паттернов ──

def extract_legal_refs(text: str) -> list[str]:
    """Извлечь ссылки на нормы из текста.
    Поддерживает оба формата:
    - Новый: [[NORM:uuid]] маркеры
    - Старый: ст. X, п. X, ч. X (для final_text / ручных правок)
    """
    refs = []
    # Новый формат: [[NORM:uuid]] (регистронезависимый — DeepSeek может вернуть uppercase)
    refs.extend(r.lower() for r in re.findall(r"\[\[NORM:([a-fA-F0-9\-]{36})\]\]", text))
    # Старый формат (в final_text и ручных правках)
    # Покрываем все падежные формы: статья/статьи/статью/статье/статьёй/статьях/статей
    patterns = [
        r"ст(?:ать[а-яё]*|атей|\.)\s*\d+(?:\.\d+)?",
        r"п(?:ункт[а-яё]*|\.)\s*\d+(?:\.\d+)?",
        r"ч(?:аст[а-яё]*|\.)\s*\d+",
    ]
    for pat in patterns:
        refs.extend(re.findall(pat, text, re.IGNORECASE))
    return refs


def extract_norm_ids(text: str) -> set[str]:
    """Извлечь только UUID из [[NORM:uuid]] маркеров (нормализовано в lowercase)."""
    return set(uid.lower() for uid in re.findall(r"\[\[NORM:([a-fA-F0-9\-]{36})\]\]", text))


def analyze_patterns(diffs: list[dict]) -> dict:
    """Анализ паттернов по массиву diff'ов."""
    added_refs = Counter()
    removed_refs = Counter()
    common_additions = Counter()
    common_removals = Counter()

    for d in diffs:
        for line in d.get("added", []):
            refs = extract_legal_refs(line)
            for r in refs:
                added_refs[r.lower().strip()] += 1
            if len(line) > 20:
                common_additions[line[:100]] += 1

        for line in d.get("removed", []):
            refs = extract_legal_refs(line)
            for r in refs:
                removed_refs[r.lower().strip()] += 1

    return {
        "frequently_added_refs": added_refs.most_common(20),
        "frequently_removed_refs": removed_refs.most_common(20),
        "common_additions": common_additions.most_common(10),
        "avg_edit_distance": sum(d["edit_distance"] for d in diffs) / len(diffs) if diffs else 0,
    }


# ── 3. Менеджер эталонов ──

async def find_exemplars(db: AsyncSession, threshold: int = 50):
    """Найти дела с минимальными правками — кандидаты в эталоны."""
    cases = (await db.execute(
        select(Case).where(
            Case.status == "completed",
            Case.generated_text.isnot(None),
            Case.final_text.isnot(None),
        ).order_by(Case.updated_at.desc()).limit(500)
    )).scalars().all()

    new_exemplars = 0
    for case in cases:
        if not case.generated_text or not case.final_text:
            continue

        # Уже есть эталон?
        existing = (await db.execute(
            select(Exemplar).where(Exemplar.case_id == case.id)
        )).scalar_one_or_none()
        if existing:
            continue

        dist = compute_edit_distance(case.generated_text, case.final_text)
        total_words = len(case.generated_text.split())
        ratio = dist / total_words if total_words > 0 else 1

        if ratio < 0.05:  # менее 5% изменений
            db.add(Exemplar(
                case_id=case.id,
                generated_text=case.generated_text,
                final_text=case.final_text,
                edit_distance=dist,
            ))
            new_exemplars += 1

    await db.commit()
    log.info(f"Новых эталонов: {new_exemplars}")
    return new_exemplars


# ── 4. Профилировщик стиля ──

async def update_style_profiles(db: AsyncSession):
    """Обновить style_profile для активных пользователей."""
    from collections import defaultdict

    # Один запрос: все completed cases с final_text для активных пользователей.
    # Ранжируем по updated_at desc внутри каждого user_id, берём top-20 через window function.
    row_num = func.row_number().over(
        partition_by=Case.user_id,
        order_by=Case.updated_at.desc(),
    ).label("rn")
    subq = (
        select(Case, row_num)
        .join(User, Case.user_id == User.id)
        .where(
            User.is_active == True,
            Case.status == "completed",
            Case.final_text.isnot(None),
        )
        .subquery()
    )
    all_cases = (await db.execute(
        select(Case).join(subq, Case.id == subq.c.id).where(subq.c.rn <= 20)
    )).scalars().all()

    # Группируем по user_id
    cases_by_user: dict[int, list] = defaultdict(list)
    for c in all_cases:
        cases_by_user[c.user_id].append(c)

    if not cases_by_user:
        log.info("Обновлено профилей: 0")
        return

    # Загружаем только тех пользователей, у которых есть completed cases
    users = (await db.execute(
        select(User).where(User.id.in_(list(cases_by_user.keys())))
    )).scalars().all()

    updated = 0
    for user in users:
        cases = cases_by_user.get(user.id, [])

        if len(cases) < 3:
            continue

        diffs = []
        for c in cases:
            if c.generated_text and c.final_text:
                diffs.append(get_diff_details(c.generated_text, c.final_text))

        if not diffs:
            continue

        patterns = analyze_patterns(diffs)

        profile = {
            "preferred_refs": [r for r, _ in patterns["frequently_added_refs"][:10]],
            "avoided_refs": [r for r, _ in patterns["frequently_removed_refs"][:10]],
            "avg_edit_ratio": patterns["avg_edit_distance"],
            "cases_analyzed": len(diffs),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        user.style_profile = profile
        updated += 1

    await db.commit()
    log.info(f"Обновлено профилей: {updated}")


# ── 5. Краудсорсинг норм ──

async def detect_added_norms(db: AsyncSession):
    """Найти нормы, добавленные судьями в правках.
    
    Сравнивает текстовые ссылки (ст. X) в final_text с тем, что было в generated_text.
    Важно: generated_text содержит [[NORM:uuid]] маркеры, а final_text — развёрнутый текст.
    Поэтому для generated_text мы резолвим UUID'ы в short_ref'ы через validation_result.
    """
    cases = (await db.execute(
        select(Case).where(
            Case.status == "completed",
            Case.generated_text.isnot(None),
            Case.final_text.isnot(None),
        ).order_by(Case.updated_at.desc()).limit(200)
    )).scalars().all()

    new_assoc = 0
    for case in cases:
        # Из generated_text: резолвим [[NORM:uuid]] в текстовые short_ref'ы
        gen_text_refs = set()
        if case.validation_result and "references" in case.validation_result:
            for ref in case.validation_result["references"]:
                short = ref.get("short_ref", "")
                if short:
                    # Извлекаем текстовые ссылки из short_ref (ст. X, п. Y)
                    gen_text_refs.update(extract_legal_refs(short))
        # Также добавляем текстовые ссылки, написанные ВНЕ маркеров (если модель нарушила промпт)
        # Убираем UUID'ы — они не являются текстовыми ссылками
        for r in extract_legal_refs(case.generated_text):
            if len(r) < 36:  # не UUID
                gen_text_refs.add(r)

        # Из final_text: текстовые ссылки (ст. X, п. Y)
        fin_text_refs = set()
        for r in extract_legal_refs(case.final_text):
            if len(r) < 36:  # не UUID
                fin_text_refs.add(r)

        # Разница — то, что судья ДЕЙСТВИТЕЛЬНО добавил вручную
        added = fin_text_refs - gen_text_refs

        if not added or not case.fact_pack:
            continue

        keywords = case.fact_pack.get("keywords", [])[:10]
        if not keywords:
            continue

        for ref in added:
            # Экранируем LIKE-специальные символы (%, _) для безопасного поиска
            safe_ref = ref.replace("%", "\\%").replace("_", "\\_")
            # Ищем норму в базе
            norm = (await db.execute(
                select(LegalNorm).where(LegalNorm.article.ilike(f"%{safe_ref}%")).limit(1)
            )).scalar_one_or_none()

            if norm:
                # Обновляем или создаём ассоциацию
                assoc = (await db.execute(
                    select(NormAssociation).where(
                        NormAssociation.norm_id == norm.id,
                        NormAssociation.fact_keywords == keywords,
                    )
                )).scalar_one_or_none()

                if assoc:
                    assoc.frequency += 1
                else:
                    db.add(NormAssociation(fact_keywords=keywords, norm_id=norm.id))
                    new_assoc += 1

    await db.commit()
    log.info(f"Новых ассоциаций: {new_assoc}")


# ── 6. Детектор галлюцинаций ──

async def detect_hallucinations(db: AsyncSession):
    """Найти ссылки, удалённые судьями (потенциальные галлюцинации).
    Сравнивает [[NORM:uuid]] маркеры в generated_text с final_text.
    Переанализирует дела, обновлённые после последнего анализа.
    """
    # Подзапрос: для каждого case_id — время последнего анализа
    last_analyzed = (
        select(
            HallucinationLog.case_id,
            func.max(HallucinationLog.created_at).label("last_at")
        ).group_by(HallucinationLog.case_id).subquery()
    )
    
    # Берём дела, которые ЛИБО ещё не анализировались, ЛИБО обновлены после анализа
    cases = (await db.execute(
        select(Case)
        .outerjoin(last_analyzed, Case.id == last_analyzed.c.case_id)
        .where(
            Case.status == "completed",
            Case.generated_text.isnot(None),
            Case.final_text.isnot(None),
        )
        .where(
            # Не анализировалось (NULL) ИЛИ case обновлён после анализа
            db_or(
                last_analyzed.c.last_at.is_(None),
                Case.updated_at > last_analyzed.c.last_at,
            )
        )
        .order_by(Case.updated_at.desc()).limit(500)
    )).scalars().all()

    new_logs = 0
    for case in cases:
        if not case.generated_text or not case.final_text:
            continue

        # Если validation_result сброшен (например, после refine) — пропускаем.
        # Без validation_result невозможно определить какие нормы были валидными,
        # и ВСЕ нормы из generated_text будут ложно помечены как галлюцинации.
        if not case.validation_result or "references" not in case.validation_result:
            continue

        # Если дело переанализируется (updated_at > last_analyzed), удаляем старые записи.
        # Без этого: старый sentinel __NO_HALLUCINATIONS__ помешает записи новых логов,
        # а старые ref-записи будут дубликатами.
        old_logs = (await db.execute(
            select(HallucinationLog).where(HallucinationLog.case_id == case.id)
        )).scalars().all()
        if old_logs:
            for ol in old_logs:
                await db.delete(ol)

        # Сравниваем [[NORM:uuid]] маркеры в generated_text
        gen_norm_ids = extract_norm_ids(case.generated_text)

        # В final_text маркеры развёрнуты в человекочитаемый текст (ст. 395 ГК РФ).
        # Если судья УДАЛИЛ ссылку, соответствующий текст пропадёт из final_text.
        # Проверяем через validation_result.short_ref — ищем его в final_text.
        final_norm_ids = set()
        if case.validation_result and "references" in case.validation_result:
            for ref in case.validation_result["references"]:
                short = ref.get("short_ref", "")
                nid = ref.get("norm_id", "")
                status = ref.get("status", "")

                # RED-статус (фейковый UUID / не найдено в БД) — это ТОЧНО галлюцинация.
                # Не добавляем в final_norm_ids → попадёт в removed_norms → будет залогирован.
                if status == "red":
                    continue

                if short:
                    # GREEN/YELLOW норма: считается сохранённой если short_ref есть в final_text
                    if short in case.final_text:
                        final_norm_ids.add(nid)
                # Нет short_ref но не RED → edge case, считаем сохранённой чтобы не шуметь
                elif status != "red":
                    final_norm_ids.add(nid)

        # UUID-ы которые были в generated_text но удалены судьёй из final_text
        removed_norms = gen_norm_ids - final_norm_ids

        # Текстовые ссылки (ст. X): не сравниваем generated_text с final_text напрямую,
        # т.к. generated_text содержит [[NORM:uuid]], а final_text — развёрнутый текст.
        # Этот путь обрабатывается через UUID-сравнение выше.

        all_removed = removed_norms

        for ref in all_removed:
            # UUID — проверяем в таблице legal_norms, текст — по article
            if len(ref) == 36 and "-" in ref:
                try:
                    ref_uuid = PyUUID(ref)
                except (ValueError, AttributeError):
                    ref_uuid = None
                if ref_uuid:
                    in_base = (await db.execute(
                        select(func.count()).select_from(LegalNorm)
                        .where(LegalNorm.id == ref_uuid)
                    )).scalar() > 0
                else:
                    in_base = False
            else:
                safe_ref = ref.replace("%", "\\%").replace("_", "\\_")
                in_base = (await db.execute(
                    select(func.count()).select_from(LegalNorm)
                    .where(LegalNorm.article.ilike(f"%{safe_ref}%"))
                )).scalar() > 0

            db.add(HallucinationLog(
                case_id=case.id,
                reference_text=ref,
                was_in_base=in_base,
            ))
            new_logs += 1

        # Sentinel: если 0 галлюцинаций — помечаем дело как обработанное
        # (старые записи уже удалены выше при переанализе)
        if not all_removed:
            db.add(HallucinationLog(
                case_id=case.id,
                reference_text="__NO_HALLUCINATIONS__",
                was_in_base=True,
            ))

    await db.commit()
    log.info(f"Новых логов галлюцинаций: {new_logs}")


# ── 7. Ночной cron ──

async def nightly_job():
    """Ночной анализ. Запуск: 0 3 * * * python -m app.services.learning"""
    log.info("=" * 50)
    log.info("НОЧНОЙ АНАЛИЗ САМООБУЧЕНИЯ")
    log.info("=" * 50)

    async with async_session() as db:
        for step_name, step_func in [
            ("1/4 Поиск эталонов", find_exemplars),
            ("2/4 Обновление стилевых профилей", update_style_profiles),
            ("3/4 Краудсорсинг норм", detect_added_norms),
            ("4/4 Детекция галлюцинаций", detect_hallucinations),
        ]:
            log.info(f"\n{step_name}...")
            try:
                await step_func(db)
            except Exception:
                log.error(f"Шаг '{step_name}' упал", exc_info=True)

    log.info("\nНочной анализ завершён")


if __name__ == "__main__":
    asyncio.run(nightly_job())
