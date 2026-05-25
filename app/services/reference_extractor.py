"""
Извлечение ссылок на нормы права из сгенерированного текста.

Парсит plain text (не [[NORM:uuid]] маркеры) и находит:
- Кодексы:  "ст. 395 ГК РФ", "п. 1 ст. 15 ГК РФ", "ч. 2 ст. 330 ГПК РФ"
- Пленумы:  "Постановление Пленума ВС РФ от 28.06.2012 № 17"
- Решения ВС: "Определение ВС РФ от 12.03.2024 № 305-ЭС24-1234"
- Сокращения: "ППВС от 28.06.2012 №17", "ППВС №17"

Используется AI-ревизором для верификации корректности ссылок.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Кодексы РФ (короткие названия) ────────────────────────────────
CODEX_NAMES = {
    "ГК":   "Гражданский кодекс РФ",
    "ГПК":  "Гражданский процессуальный кодекс РФ",
    "АПК":  "Арбитражный процессуальный кодекс РФ",
    "УК":   "Уголовный кодекс РФ",
    "УПК":  "Уголовно-процессуальный кодекс РФ",
    "КоАП": "Кодекс об административных правонарушениях РФ",
    "СК":   "Семейный кодекс РФ",
    "ТК":   "Трудовой кодекс РФ",
    "ЖК":   "Жилищный кодекс РФ",
    "НК":   "Налоговый кодекс РФ",
    "ЗК":   "Земельный кодекс РФ",
    "БК":   "Бюджетный кодекс РФ",
    "ВК":   "Водный кодекс РФ",
    "ЛК":   "Лесной кодекс РФ",
    "КАС":  "Кодекс административного судопроизводства РФ",
}

CODEX_SHORT_RE = "|".join(re.escape(k) for k in sorted(CODEX_NAMES.keys(), key=len, reverse=True))

# Маппинг полных названий кодексов -> короткие (для "статьи 807 Гражданского кодекса РФ")
CODEX_FULL_NAMES_MAP = {
    "гражданского кодекса": "ГК",
    "гражданский кодекс": "ГК",
    "гражданского процессуального кодекса": "ГПК",
    "гражданский процессуальный кодекс": "ГПК",
    "арбитражного процессуального кодекса": "АПК",
    "арбитражный процессуальный кодекс": "АПК",
    "уголовного кодекса": "УК",
    "уголовный кодекс": "УК",
    "уголовно-процессуального кодекса": "УПК",
    "уголовно-процессуальный кодекс": "УПК",
    "кодекса об административных правонарушениях": "КоАП",
    "кодекс об административных правонарушениях": "КоАП",
    "семейного кодекса": "СК",
    "семейный кодекс": "СК",
    "трудового кодекса": "ТК",
    "трудовой кодекс": "ТК",
    "жилищного кодекса": "ЖК",
    "жилищный кодекс": "ЖК",
    "налогового кодекса": "НК",
    "налоговый кодекс": "НК",
    "земельного кодекса": "ЗК",
    "земельный кодекс": "ЗК",
    "кодекса административного судопроизводства": "КАС",
    "кодекс административного судопроизводства": "КАС",
}

CODEX_FULL_RE_STR = "|".join(re.escape(k) for k in sorted(CODEX_FULL_NAMES_MAP.keys(), key=len, reverse=True))


# ─── Regex-паттерны ─────────────────────────────────────────────────

# 1a. Статьи кодексов — краткая форма: "ст. 395 ГК РФ"
CODEX_RE = re.compile(
    r"(?:"
    r"(?:п\.?\s*\d+(?:\.\d+)?\s+)?"
    r"(?:ч\.?\s*\d+\s+)?"
    r"(?:подп\.?\s*\d+\s+)?"
    r"ст\.?\s*(\d+(?:\.\d+)?)"
    r"(?:\s*,\s*\d+(?:\.\d+)?)*"
    r"\s+"
    r"(" + CODEX_SHORT_RE + r")"
    r"\s*РФ"
    r")",
    re.IGNORECASE,
)

# 1b. Статьи кодексов — полная форма: "статьей 167 ГПК РФ",
#     "статьями 194-199 ГПК РФ",
#     "статьи 807 Гражданского кодекса Российской Федерации"
CODEX_FULL_FORM_RE = re.compile(
    r"(?:"
    r"(?:п\.?\s*\d+(?:\.\d+)?\s+)?"
    r"(?:ч\.?\s*\d+\s+)?"
    r"стать[а-яёА-ЯЁ]*\s+"
    r"(\d+(?:\.\d+)?)"
    r"(?:\s*[,\u2013\-]\s*\d+(?:\.\d+)?)*"
    r"\s+"
    r"(?:"
    r"(" + CODEX_SHORT_RE + r")\s*РФ"
    r"|"
    r"(" + CODEX_FULL_RE_STR + r")\s+(?:Российской\s+Федерации|РФ)"
    r")"
    r")",
    re.IGNORECASE,
)

# 2. Пленумы ВС РФ (полная форма)
PLENUM_FULL_RE = re.compile(
    r"(?:Постановлени[еияй]\s+)"
    r"Пленума?\s+"
    r"(?:Верховного\s+Суда|ВС)\s+"
    r"(?:Российской\s+Федерации|РФ)\s+"
    r"от\s+"
    r"(\d{1,2}[\.\s]?\s*"
    r"(?:\d{2}\.\d{4}"
    r"|[а-яА-Я]+\s+\d{4})"
    r"(?:\s*г\.?)?)"
    r"\s*(?:№|N|No\.?)\s*"
    r"(\d+)",
    re.IGNORECASE,
)

# 3. ППВС (сокращённая форма)
PPVS_SHORT_RE = re.compile(
    r"ППВС\s+"
    r"(?:от\s+(\d{1,2}\.\d{2}\.\d{4})\s*)?"
    r"(?:№|N|No\.?)\s*(\d+)"
    r"(?:\s+п\.?\s*(\d+))?",
    re.IGNORECASE,
)

# 4. Пленумы с указанием пункта в начале
PLENUM_WITH_POINT_RE = re.compile(
    r"п\.?\s*(\d+)\s+"
    r"(?:Постановлени[еияй]\s+)?"
    r"Пленума?\s+"
    r"(?:Верховного\s+Суда|ВС)\s+"
    r"(?:Российской\s+Федерации|РФ)\s+"
    r"от\s+"
    r"(\d{1,2}\.\d{2}\.\d{4})"
    r"(?:\s*г\.?)?"
    r"\s*(?:№|N|No\.?)\s*"
    r"(\d+)",
    re.IGNORECASE,
)

# 5. Решения/определения ВС РФ
VS_DECISION_RE = re.compile(
    r"(Определени[еияй]|Постановлени[еияй]|Решени[еияй])\s+"
    r"(?:Судебной\s+коллегии\s+)?(?:по\s+[а-яА-Я]+\s+делам\s+)?"
    r"(?:Верховного\s+Суда|ВС)\s+"
    r"(?:Российской\s+Федерации|РФ)\s+"
    r"от\s+"
    r"(\d{1,2}\.\d{2}\.\d{4})"
    r"(?:\s*г\.?)?"
    r"\s*(?:№|N|No\.?)\s*"
    r"([\w\-/]+)",
    re.IGNORECASE,
)

# 6. Обзоры судебной практики ВС РФ (полная форма)
REVIEW_FULL_RE = re.compile(
    r"(?:п\.?\s*(\d+)\s+)?"
    r"Обзор[аеу]?\s+"
    r"(?:судебной\s+практики\s+)?"
    r"(?:Верховного\s+Суда|ВС)\s+"
    r"(?:Российской\s+Федерации|РФ)\s+"
    r"(?:№|N|No\.?)\s*"
    r"(\d+(?:\s*,\s*\d+)?)"
    r"\s*\((\d{4})\)",
    re.IGNORECASE,
)

# 6b. Сокращённая форма обзора
REVIEW_SHORT_RE = re.compile(
    r"(?:п\.?\s*(\d+)\s+)?"
    r"[Оо]бзор[аеу]?\s+"
    r"(?:ВС|Верховного\s+Суда)\s+"
    r"(?:РФ\s+)?"
    r"(?:№|N|No\.?)\s*"
    r"(\d+(?:\s*,\s*\d+)?)"
    r"\s*\((\d{4})\)",
    re.IGNORECASE,
)

# 7. Федеральные законы
FZ_RE = re.compile(
    r"(?:Федеральн(?:ый|ого)\s+закон(?:а|е|у|ом)?\s+|ФЗ\s+)"
    r"(?:от\s+(\d{1,2}\.\d{2}\.\d{4})\s*"
    r"(?:№|N|No\.?)\s*([\w\-]+)\s*)?"
    r"(?:[«\"]([^»\"]+)[»\"])?",
    re.IGNORECASE,
)


# ─── Deduplication ─────────────────────────────────────────────────

class _RefCollector:
    """Коллектор ссылок с дедупликацией по позициям (overlap resolution)."""

    def __init__(self):
        self.refs: list[dict] = []
        self._positions: set[tuple[int, int]] = set()

    def add(self, ref: dict) -> None:
        pos = ref["position"]
        end = ref["end_position"]

        for seen_start, seen_end in list(self._positions):
            if pos < seen_end and end > seen_start:
                # Пересечение — берём более длинный match
                if (end - pos) <= (seen_end - seen_start):
                    return
                # Текущий длиннее — удаляем предыдущий
                self.refs[:] = [
                    r for r in self.refs
                    if (r["position"], r["end_position"]) != (seen_start, seen_end)
                ]
                self._positions.discard((seen_start, seen_end))

        self._positions.add((pos, end))
        self.refs.append(ref)

    def sorted_refs(self) -> list[dict]:
        return sorted(self.refs, key=lambda r: r["position"])


# ─── Per-type extractors ───────────────────────────────────────────

def _extract_plenum_refs(text: str, collector: _RefCollector) -> None:
    """Извлекает ссылки на пленумы (полные, сокращённые, с пунктом)."""
    # Пленумы с пунктом в начале (п. 25 ППВС от ... № ...)
    for m in PLENUM_WITH_POINT_RE.finditer(text):
        collector.add({
            "raw": m.group(0).strip(),
            "type": "plenum",
            "number": m.group(3),
            "date": m.group(2),
            "paragraph": m.group(1),
            "position": m.start(),
            "end_position": m.end(),
        })

    # Пленумы (полная форма)
    for m in PLENUM_FULL_RE.finditer(text):
        collector.add({
            "raw": m.group(0).strip(),
            "type": "plenum",
            "number": m.group(2),
            "date": _normalize_date(m.group(1)),
            "paragraph": None,
            "position": m.start(),
            "end_position": m.end(),
        })

    # ППВС (сокращённая форма)
    for m in PPVS_SHORT_RE.finditer(text):
        collector.add({
            "raw": m.group(0).strip(),
            "type": "plenum",
            "number": m.group(2),
            "date": m.group(1),
            "paragraph": m.group(3),
            "position": m.start(),
            "end_position": m.end(),
        })


def _extract_review_refs(text: str, collector: _RefCollector) -> None:
    """Извлекает ссылки на обзоры судебной практики ВС РФ."""
    for m in REVIEW_FULL_RE.finditer(text):
        collector.add({
            "raw": m.group(0).strip(),
            "type": "practice_review",
            "paragraph": m.group(1),
            "number": m.group(2).strip(),
            "year": m.group(3),
            "position": m.start(),
            "end_position": m.end(),
        })

    for m in REVIEW_SHORT_RE.finditer(text):
        collector.add({
            "raw": m.group(0).strip(),
            "type": "practice_review",
            "paragraph": m.group(1),
            "number": m.group(2).strip(),
            "year": m.group(3),
            "position": m.start(),
            "end_position": m.end(),
        })


def _extract_vs_decision_refs(text: str, collector: _RefCollector) -> None:
    """Извлекает ссылки на решения/определения ВС РФ."""
    for m in VS_DECISION_RE.finditer(text):
        collector.add({
            "raw": m.group(0).strip(),
            "type": "vs_decision",
            "act_type": m.group(1),
            "date": m.group(2),
            "number": m.group(3),
            "position": m.start(),
            "end_position": m.end(),
        })


def _extract_codex_refs(text: str, collector: _RefCollector) -> None:
    """Извлекает ссылки на статьи кодексов (краткая + полная форма)."""
    # 1a. Краткая форма: "ст. 395 ГК РФ"
    for m in CODEX_RE.finditer(text):
        raw = m.group(0).strip()
        codex_short = m.group(2).upper()
        if codex_short == "КОАП":
            codex_short = "КоАП"

        collector.add({
            "raw": raw,
            "type": "codex",
            "codex": codex_short,
            "codex_full": CODEX_NAMES.get(codex_short, codex_short + " РФ"),
            "article": m.group(1),
            "paragraph": _extract_paragraph(raw),
            "part": _extract_part(raw),
            "position": m.start(),
            "end_position": m.end(),
        })

    # 1b. Полная форма: "статьей 167 ГПК РФ", "статьи 807 Гражданского кодекса РФ"
    for m in CODEX_FULL_FORM_RE.finditer(text):
        raw = m.group(0).strip()
        # group(2) = короткое название (ГК, ГПК...), group(3) = полное название
        if m.group(2):
            codex_short = m.group(2).upper()
            if codex_short == "КОАП":
                codex_short = "КоАП"
        elif m.group(3):
            codex_short = CODEX_FULL_NAMES_MAP.get(m.group(3).lower(), "")
        else:
            continue

        if not codex_short:
            continue

        collector.add({
            "raw": raw,
            "type": "codex",
            "codex": codex_short,
            "codex_full": CODEX_NAMES.get(codex_short, codex_short + " РФ"),
            "article": m.group(1),
            "paragraph": _extract_paragraph(raw),
            "part": _extract_part(raw),
            "position": m.start(),
            "end_position": m.end(),
        })


def _extract_fz_refs(text: str, collector: _RefCollector) -> None:
    """Извлекает ссылки на федеральные законы."""
    for m in FZ_RE.finditer(text):
        if not m.group(1) and not m.group(3):
            continue  # "ФЗ" без номера и названия — пропускаем
        collector.add({
            "raw": m.group(0).strip(),
            "type": "fz",
            "date": m.group(1),
            "number": m.group(2),
            "title": m.group(3),
            "position": m.start(),
            "end_position": m.end(),
        })


# ─── Main function ─────────────────────────────────────────────────

def extract_legal_references(text: str) -> list[dict]:
    """Извлекает все ссылки на нормы права из plain text.

    Returns: список словарей с информацией о каждой ссылке.
    Каждая ссылка содержит:
    - raw: полный текст ссылки как он встречается
    - type: "codex" | "plenum" | "vs_decision" | "practice_review" | "fz"
    - position: начальная позиция в тексте
    - end_position: конечная позиция
    - и type-специфичные поля (article, number, date, codex, paragraph)
    """
    collector = _RefCollector()

    # Порядок важен: длинные паттерны сначала (приоритет при overlap)
    _extract_plenum_refs(text, collector)
    _extract_review_refs(text, collector)
    _extract_vs_decision_refs(text, collector)
    _extract_codex_refs(text, collector)
    _extract_fz_refs(text, collector)

    refs = collector.sorted_refs()

    logger.info(
        "Extracted %d legal references: codex=%d, plenum=%d, vs_decision=%d, review=%d, fz=%d",
        len(refs),
        sum(1 for r in refs if r["type"] == "codex"),
        sum(1 for r in refs if r["type"] == "plenum"),
        sum(1 for r in refs if r["type"] == "vs_decision"),
        sum(1 for r in refs if r["type"] == "practice_review"),
        sum(1 for r in refs if r["type"] == "fz"),
    )
    return refs


# ─── Utilities ─────────────────────────────────────────────────────

_MONTHS = {
    "января": "01", "февраля": "02", "марта": "03",
    "апреля": "04", "мая": "05", "июня": "06",
    "июля": "07", "августа": "08", "сентября": "09",
    "октября": "10", "ноября": "11", "декабря": "12",
}


def _normalize_date(date_str: str) -> Optional[str]:
    """Нормализует дату из различных форматов в DD.MM.YYYY."""
    if not date_str:
        return None

    date_str = date_str.strip().rstrip(".")

    if re.match(r"^\d{1,2}\.\d{2}\.\d{4}$", date_str):
        return date_str

    m = re.match(r"(\d{1,2})\s+([а-яА-Я]+)\s+(\d{4})", date_str)
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month:
            return f"{m.group(1).zfill(2)}.{month}.{m.group(3)}"

    return date_str


def _extract_paragraph(raw: str) -> Optional[str]:
    """Извлекает номер пункта из строки вроде 'п. 1 ст. 15 ГК РФ'."""
    m = re.match(r"п\.?\s*(\d+(?:\.\d+)?)", raw, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_part(raw: str) -> Optional[str]:
    """Извлекает номер части из строки вроде 'ч. 2 ст. 330 ГПК РФ'."""
    m = re.search(r"ч\.?\s*(\d+)", raw, re.IGNORECASE)
    return m.group(1) if m else None


def get_sentence_around_ref(text: str, position: int, end_position: int) -> str:
    """Извлекает полное предложение, содержащее ссылку.

    Нужно для AI-ревизора: чтобы проверить контекст использования нормы,
    ему нужно видеть целое предложение, а не только ссылку.
    """
    # Начало предложения
    sentence_start = position
    for i in range(position - 1, max(0, position - 500), -1):
        if text[i] in ".!?\n" and i < position - 1:
            sentence_start = i + 1
            break
    else:
        sentence_start = max(0, position - 500)

    # Конец предложения
    sentence_end = end_position
    for i in range(end_position, min(len(text), end_position + 500)):
        if text[i] in ".!?\n":
            sentence_end = i + 1
            break
    else:
        sentence_end = min(len(text), end_position + 500)

    return text[sentence_start:sentence_end].strip()
