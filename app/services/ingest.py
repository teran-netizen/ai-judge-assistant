"""
Модуль 1: Ingest — обработка файлов дела.

Pipeline v3 (async OCR + parallel DeepSeek):
  1. Classify: определить тип файлов (текст / изображения для OCR)
  2. OCR batch: все изображения параллельно через Yandex async API (10 RPS)
  3. DeepSeek extract: все документы параллельно (до 30 concurrent)
  4. Compile summary: один вызов DeepSeek

Тесты (реальные замеры на продакшене):
  - Yandex OCR async: 10 RPS submit, 10 изображений за ~5s, 40 за ~8s
  - DeepSeek API: 30+ параллельных без деградации, ~27s/запрос

Для 40 фото: ~8s OCR + ~54s DeepSeek (40/30×27÷... overlap) ≈ ~60s total.
"""

import hashlib
import json
import logging
import asyncio
import time
from pathlib import Path
from typing import AsyncGenerator, Callable, Awaitable

import httpx

from app.services.deepseek import deepseek
from app.services.extract_prompts import build_extract_messages, build_brief_from_documents
from app.services.case_context import (
    empty_context,
    is_duplicate,
    add_document,
    compile_summary,
    _parse_json_response,
)

logger = logging.getLogger(__name__)

# Минимальное количество символов OCR-текста, чтобы считать документ читаемым
MIN_OCR_CHARS = 20

# Максимальный размер OCR-текста для одного документа (защита от переполнения контекста)
MAX_SINGLE_DOC_CHARS = 60_000  # ~20K токенов

# DeepSeek extraction concurrency — тесты показали 30+ без деградации
EXTRACT_CONCURRENCY = 30

# Параллельная конвертация PDF→PNG (CPU-bound, ограничиваем чтобы не перегружать)
PDF_CONVERT_CONCURRENCY = 12


async def _extract_text_from_file(file_path: str, filename: str) -> tuple[str, list[str]]:
    """
    Извлекает текст из файла. Возвращает (text, image_paths).

    - PDF с текстовым слоем → текст напрямую
    - PDF-скан → конвертация в PNG → список путей для OCR
    - Изображения → путь для OCR
    - docx/doc/txt → текст напрямую
    """
    path = Path(file_path)
    if not path.exists():
        return "", []

    ext = path.suffix.lower()

    if ext == ".pdf":
        from app.services.pipeline import _extract_pdf_text
        from app.services.pdf_converter import convert_pdf_to_images

        pdf_text = await _extract_pdf_text(str(path))
        page_count = max(1, pdf_text.count(chr(12)) + 1) if pdf_text else 1
        chars_per_page = len(pdf_text.strip()) / page_count if pdf_text.strip() else 0

        if chars_per_page > 50:
            logger.info(f"PDF {filename}: текстовый слой ({len(pdf_text)} симв)")
            return pdf_text.strip(), []
        else:
            output_dir = path.parent / f"{path.stem}_pages"
            png_paths = await convert_pdf_to_images(str(path), str(output_dir))
            logger.info(f"PDF {filename}: скан, {len(png_paths)} страниц для OCR")
            return "", png_paths

    elif ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tiff", ".tif"):
        return "", [str(path)]

    elif ext == ".txt":
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return text.strip(), []
        except Exception as e:
            logger.warning(f"Не удалось прочитать {filename}: {e}")
            return "", []

    elif ext == ".docx":
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(str(path))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return text.strip(), []
        except Exception as e:
            logger.warning(f"Не удалось прочитать {filename}: {e}")
            return "", []

    elif ext == ".doc":
        try:
            import subprocess
            result = await asyncio.to_thread(
                subprocess.run,
                ["antiword", str(path)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip(), []
            else:
                logger.warning(f"antiword не смог прочитать {filename}")
                return "", []
        except Exception as e:
            logger.warning(f"Не удалось прочитать .doc {filename}: {e}")
            return "", []

    else:
        logger.info(f"Файл {filename} ({ext}) — не поддержан, пропускаем")
        return "", []


async def _extract_with_deepseek(
    text: str,
    filename: str,
    context_snapshot: dict,
) -> dict:
    """
    DeepSeek extraction для одного документа.
    Использует context_snapshot (иммутабельный) для формирования промпта.

    Returns:
        dict с extracted JSON или None при ошибке.
    """
    documents = context_snapshot.get("documents", [])
    if documents:
        brief = build_brief_from_documents(documents)
        case_context_block = f"КОНТЕКСТ ДЕЛА (уже обработанные документы):\n{brief}"
        from app.services.extract_prompts import BASE_EXTRACT_SYSTEM, BASE_EXTRACT_USER
        user_content = BASE_EXTRACT_USER.format(
            case_context_block=case_context_block,
            ocr_text=text,
            type_addition="",
        )
        messages = [
            {"role": "system", "content": BASE_EXTRACT_SYSTEM},
            {"role": "user", "content": user_content},
        ]
    else:
        summary = context_snapshot.get("summary", {})
        messages = build_extract_messages(
            case_summary=summary,
            ocr_text=text,
            doc_type_hint=None,
        )

    result = await deepseek.chat(messages, max_tokens=4096, temperature=0.1)
    content = result["content"]

    extracted = _parse_json_response(content)
    if not extracted:
        logger.warning("Не удалось распарсить извлечение для %s, пробуем JSON repair retry", filename)
        repair_messages = messages + [
            {"role": "assistant", "content": content[:12000]},
            {
                "role": "user",
                "content": (
                    "Предыдущий ответ не был валидным JSON. "
                    "Верни только один валидный JSON-объект по той же схеме, "
                    "без Markdown, без пояснений и без текста вокруг JSON."
                ),
            },
        ]
        try:
            retry_result = await deepseek.chat(repair_messages, max_tokens=4096, temperature=0.0)
            extracted = _parse_json_response(retry_result.get("content", ""))
        except Exception as retry_error:
            logger.error("JSON repair retry ошибка для %s: %s", filename, retry_error)
            extracted = None

        if not extracted:
            logger.error(f"Не удалось распарсить извлечение для {filename}")
            return None

    if not extracted.get("summary_line"):
        doc_type_label = _doc_type_label(extracted.get("doc_type", "other"))
        extracted["summary_line"] = f"{doc_type_label} ({filename})"

    return extracted


async def process_single_file(
    file_path: str,
    filename: str,
    case_context: dict,
    on_ocr_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> dict:
    """
    Обрабатывает один файл: OCR → извлечение → результат.
    Standalone-версия (для совместимости). Pipeline использует process_batch_streaming.
    """
    try:
        text, image_paths = await _extract_text_from_file(file_path, filename)

        if image_paths:
            from app.services.ocr import recognize_async_batch
            ocr_results = await recognize_async_batch(image_paths)
            text = "\n\n".join(t for t in ocr_results if t.strip())

        if not text or len(text.strip()) < MIN_OCR_CHARS:
            return {
                "status": "unreadable",
                "error": f"Не удалось распознать текст (получено {len(text.strip())} символов)",
                "ocr_text_hash": "",
                "ocr_chars": len(text.strip()),
            }

        if len(text) > MAX_SINGLE_DOC_CHARS:
            text = text[:MAX_SINGLE_DOC_CHARS] + "\n\n[Текст обрезан — документ слишком длинный]"

        ocr_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        dup_filename = is_duplicate(case_context, ocr_hash)
        if dup_filename:
            return {
                "status": "duplicate",
                "duplicate_of": dup_filename,
                "ocr_text_hash": ocr_hash,
                "ocr_chars": len(text),
            }

        extracted = await _extract_with_deepseek(text, filename, case_context)
        if not extracted:
            return {
                "status": "error",
                "error": "Не удалось распарсить ответ ИИ",
                "ocr_text_hash": ocr_hash,
                "ocr_chars": len(text),
            }

        return {
            "status": "ok",
            "extracted": extracted,
            "ocr_text": text,
            "ocr_text_hash": ocr_hash,
            "ocr_chars": len(text),
        }

    except Exception as e:
        logger.exception(f"Ошибка обработки {filename}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "ocr_text_hash": "",
            "ocr_chars": 0,
        }


async def process_batch_streaming(
    case_id: str,
    unprocessed_files: list,
    case_context: dict,
    emit_checkpoints: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Pipeline v3: async OCR batch + parallel DeepSeek extract.

    Архитектура:
      Phase 1 (Classify):  определить тип каждого файла (мгновенно)
      Phase 2 (OCR batch): все изображения параллельно через Yandex async (10 RPS)
                           SSE: processing → ocr_progress → ocr_done
      Phase 3 (Extract):   все документы параллельно через DeepSeek (30 concurrent)
                           SSE: doc_done / doc_error / doc_skip
      Phase 4 (Summary):   compile_summary одним вызовом DeepSeek

    40 фото: ~8s OCR + ~40s DeepSeek ≈ ~50s (vs ~119s в v2)
    """
    from app.services.ocr import recognize_async_batch
    from app.config import get_settings

    total = len(unprocessed_files)

    # Иммутабельный снимок контекста для промптов DeepSeek
    context_snapshot = {
        "documents": list(case_context.get("documents", [])),
        "summary": case_context.get("summary", {}),
        "doc_count": case_context.get("doc_count", 0),
        "total_chars": case_context.get("total_chars", 0),
    }

    settings = get_settings()

    # ─── Phase 1: Classify files (parallel PDF conversion) ─────────
    # Классификация + конвертация PDF→PNG параллельно (семафор PDF_CONVERT_CONCURRENCY)
    file_entries = [None] * total  # [{idx, filename, text, image_paths}]
    classify_sem = asyncio.Semaphore(PDF_CONVERT_CONCURRENCY)
    classify_done = {"count": 0}
    classify_queue: asyncio.Queue = asyncio.Queue()

    async def _classify_file(idx: int, case_file):
        filename = case_file.filename
        file_path = case_file.file_path
        async with classify_sem:
            cached_text = getattr(case_file, "ocr_text", None)
            if cached_text and cached_text.strip():
                text, image_paths = cached_text, []
                logger.info(
                    "Using cached OCR text for %s (%d chars)",
                    filename,
                    len(cached_text),
                )
            else:
                try:
                    text, image_paths = await _extract_text_from_file(file_path, filename)
                except Exception as e:
                    logger.error(f"Classify ошибка для {filename}: {e}")
                    text, image_paths = "", []
            await classify_queue.put((idx, filename, text, image_paths))

    # Запускаем все классификации параллельно
    classify_tasks = [
        asyncio.create_task(_classify_file(idx, cf))
        for idx, cf in enumerate(unprocessed_files)
    ]

    # Читаем результаты по мере готовности
    for _ in range(total):
        idx, filename, text, image_paths = await classify_queue.get()
        classify_done["count"] += 1
        pct = int((classify_done["count"] / total) * 10)  # 0-10%
        file_entries[idx] = {
            "idx": idx,
            "filename": filename,
            "text": text,
            "image_paths": image_paths,
        }
        yield _sse_event({
            "type": "processing",
            "filename": filename,
            "index": idx,
            "total": total,
            "progress_pct": pct,
            "stage_label": "Классификация файлов",
        })

    # Дожидаемся завершения всех задач (на случай исключений)
    await asyncio.gather(*classify_tasks, return_exceptions=True)

    # ─── Phase 2: Batch async OCR ────────────────────────────────
    # Собираем ВСЕ изображения из всех файлов в один плоский список
    all_images = []   # (file_idx, page_idx, image_path)
    for entry in file_entries:
        for page_idx, img_path in enumerate(entry["image_paths"]):
            all_images.append((entry["idx"], page_idx, img_path))

    if all_images:
        image_paths_flat = [img for _, _, img in all_images]
        total_images = len(image_paths_flat)
        logger.info(f"OCR async batch: {total_images} изображений из {total} файлов")

        yield _sse_event({
            "type": "ocr_progress",
            "message": f"Распознавание {total_images} страниц...",
            "total_images": total_images,
            "completed_images": 0,
            "progress_pct": 10,
            "stage_label": "Распознавание текста (OCR)",
        })

        # Счётчик завершённых OCR (для SSE прогресса)
        ocr_completed = {"count": 0}

        async def _on_ocr_done(img_idx: int, text: str):
            ocr_completed["count"] += 1

        t0 = time.monotonic()
        ocr_results = await recognize_async_batch(
            image_paths_flat,
            api_key=settings.yandex_ocr_api_key,
            on_single_done=_on_ocr_done,
        )
        ocr_elapsed = time.monotonic() - t0

        logger.info(f"OCR async batch завершён: {total_images} стр за {ocr_elapsed:.1f}s")

        yield _sse_event({
            "type": "ocr_done",
            "filename": "",
            "index": 0,
            "total": total,
            "ocr_chars": sum(len(t) for t in ocr_results),
            "ocr_images": total_images,
            "ocr_elapsed": round(ocr_elapsed, 1),
            "progress_pct": 40,
            "stage_label": "Извлечение данных из документов",
        })

        # Маппим OCR результаты обратно к файлам
        # file_pages[file_idx] = [text_page0, text_page1, ...]
        file_pages: dict[int, list[tuple[int, str]]] = {}
        for (file_idx, page_idx, _), ocr_text in zip(all_images, ocr_results):
            if file_idx not in file_pages:
                file_pages[file_idx] = []
            file_pages[file_idx].append((page_idx, ocr_text))

        # Собираем текст для каждого файла (страницы в правильном порядке)
        for file_idx, pages in file_pages.items():
            pages.sort(key=lambda x: x[0])
            parts = [text for _, text in pages if text.strip()]
            combined = "\n\n".join(parts)

            # Обрезка
            if len(combined) > MAX_SINGLE_DOC_CHARS:
                combined = combined[:MAX_SINGLE_DOC_CHARS] + "\n\n[Текст обрезан]"

            file_entries[file_idx]["text"] = combined

    # ─── Phase 3: DeepSeek extract (parallel) ─────────────────────
    extract_sem = asyncio.Semaphore(EXTRACT_CONCURRENCY)
    sse_queue: asyncio.Queue = asyncio.Queue()
    done_count = 0

    async def _run_extract(entry: dict):
        """DeepSeek extraction в параллельном пуле."""
        idx = entry["idx"]
        filename = entry["filename"]
        text = entry["text"]

        # Проверка: текст читаемый?
        text_stripped = text.strip() if text else ""
        if len(text_stripped) < MIN_OCR_CHARS:
            await sse_queue.put(("doc_error", idx, filename, {
                "error": f"Не удалось распознать текст ({len(text_stripped)} символов)",
                "error_code": "unreadable_text",
                "ocr_text": text or "",
                "ocr_chars": len(text_stripped),
                "ocr_text_hash": hashlib.sha256((text or "").encode("utf-8")).hexdigest() if text else "",
            }))
            return

        # Проверка дубликатов
        ocr_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        dup_filename = is_duplicate(case_context, ocr_hash)
        if dup_filename:
            await sse_queue.put(("doc_skip", idx, filename, {
                "duplicate_of": dup_filename,
            }))
            return

        # DeepSeek extraction
        async with extract_sem:
            try:
                extracted = await _extract_with_deepseek(text, filename, context_snapshot)
                if extracted:
                    await sse_queue.put(("doc_ok", idx, filename, {
                        "extracted": extracted,
                        "ocr_text": text,
                        "ocr_text_hash": ocr_hash,
                        "ocr_chars": len(text),
                    }))
                else:
                    await sse_queue.put(("doc_error", idx, filename, {
                        "error": "Не удалось распарсить ответ ИИ",
                        "error_code": "extract_parse_failed",
                        "ocr_text": text,
                        "ocr_chars": len(text),
                        "ocr_text_hash": ocr_hash,
                    }))
            except Exception as e:
                logger.error(f"DeepSeek extract ошибка для {filename}: {e}")
                await sse_queue.put(("doc_error", idx, filename, {
                    "error": str(e),
                    "error_code": "extract_exception",
                    "ocr_text": text,
                    "ocr_chars": len(text),
                    "ocr_text_hash": ocr_hash,
                }))

    # Запускаем все extraction-ы параллельно
    extract_tasks = [asyncio.create_task(_run_extract(entry)) for entry in file_entries]

    # Sentinel: когда все задачи завершатся
    async def _wait_and_signal():
        await asyncio.gather(*extract_tasks, return_exceptions=True)
        await sse_queue.put(("all_done", -1, "", None))

    asyncio.create_task(_wait_and_signal())

    # Consumer: читаем из очереди и yield-им SSE
    while True:
        msg_type, idx, filename, data = await sse_queue.get()

        if msg_type == "all_done":
            break

        elif msg_type == "doc_ok":
            done_count += 1
            case_context = await add_document(
                case_context=case_context,
                extracted=data["extracted"],
                filename=filename,
                ocr_text_hash=data["ocr_text_hash"],
                ocr_chars=data["ocr_chars"],
                ocr_text=data.get("ocr_text", ""),
                skip_summary=True,
            )
            pct = 40 + int((done_count / total) * 50)  # 40-90%
            yield _sse_event({
                "type": "doc_done",
                "filename": filename,
                "doc_type": data["extracted"].get("doc_type", "other"),
                "summary_line": data["extracted"].get("summary_line", filename),
                "index": idx,
                "total": total,
                "completed": done_count,
                "progress_pct": pct,
                "stage_label": "Извлечение данных из документов",
            })

        elif msg_type == "doc_skip":
            done_count += 1
            pct = 40 + int((done_count / total) * 50)
            yield _sse_event({
                "type": "doc_skip",
                "filename": filename,
                "reason": f"Дубликат {data['duplicate_of']}",
                "index": idx,
                "total": total,
                "completed": done_count,
                "progress_pct": pct,
                "stage_label": "Извлечение данных из документов",
            })

        elif msg_type == "doc_error":
            done_count += 1
            pct = 40 + int((done_count / total) * 50)
            if emit_checkpoints:
                yield _sse_event({
                    "type": "doc_checkpoint",
                    "filename": filename,
                    "ocr_status": "error",
                    "error": data.get("error", "Неизвестная ошибка"),
                    "error_code": data.get("error_code", "extract_error"),
                    "ocr_text": data.get("ocr_text", ""),
                    "ocr_chars": data.get("ocr_chars", 0),
                    "ocr_text_hash": data.get("ocr_text_hash", ""),
                })
            yield _sse_event({
                "type": "doc_error",
                "filename": filename,
                "error": data.get("error", "Неизвестная ошибка"),
                "index": idx,
                "total": total,
                "completed": done_count,
                "progress_pct": pct,
                "stage_label": "Извлечение данных из документов",
            })

    # ─── Phase 4: Compile summary ────────────────────────────────
    if case_context.get("documents"):
        yield _sse_event({"type": "compiling_summary", "progress_pct": 90, "stage_label": "Формирование сводки дела"})
        try:
            case_context = await compile_summary(case_context)
            logger.info(f"Summary скомпилирован для case={case_id}")
        except Exception as e:
            logger.error(f"Ошибка компиляции summary для case={case_id}: {e}")

    # SSE: завершение батча
    yield _sse_event({
        "type": "batch_done",
        "doc_count": case_context.get("doc_count", 0),
        "total_in_case": case_context.get("doc_count", 0),
        "progress_pct": 100,
        "stage_label": "Готово",
    })


def get_unprocessed_files(case_files: list, case_context: dict) -> list:
    """
    Определяет, какие файлы ещё не обработаны.
    Сравнивает имена файлов в case_files с обработанными в case_context.documents.
    """
    if not case_context or not case_context.get("documents"):
        return list(case_files)

    processed_filenames = {
        doc.get("filename") for doc in case_context.get("documents", [])
    }

    return [f for f in case_files if f.filename not in processed_filenames]


def _sse_event(data: dict) -> str:
    """Формирует SSE-строку."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _doc_type_label(doc_type: str) -> str:
    """Человекочитаемое название типа документа."""
    labels = {
        "claim": "Исковое заявление",
        "response": "Отзыв/возражения",
        "contract": "Договор",
        "payment": "Платёжный документ",
        "expert": "Экспертиза/заключение",
        "court_order": "Судебный акт",
        "correspondence": "Переписка/претензия",
        "calculation": "Расчёт",
        "certificate": "Справка/выписка",
        "power_of_attorney": "Доверенность",
        "protocol": "Протокол",
        "photo_evidence": "Фото/скриншот",
        "admin_act": "Административный акт",
        "other": "Документ",
    }
    return labels.get(doc_type, "Документ")
