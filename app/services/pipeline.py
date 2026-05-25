import logging
import re
import asyncio
from pathlib import Path

from app.services.deepseek import deepseek
from app.prompts import PAID_PROMPT
from app.models import Case

logger = logging.getLogger(__name__)

# Лимит текста для DeepSeek (защита от переполнения контекста)
MAX_OCR_TEXT_CHARS = 120_000  # ~30K токенов


async def _extract_pdf_text(pdf_path: str) -> str:
    """Извлекает текст из PDF через pdftotext (poppler-utils). $0, мгновенно."""
    import subprocess
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return result.stdout
    except Exception as e:
        logger.warning(f"pdftotext failed for {pdf_path}: {e}")
    return ""


async def _extract_texts_from_files(case: Case) -> tuple[list[str], list[str]]:
    """
    Извлекает текст из файлов дела.
    Возвращает (doc_texts, image_paths) — тексты документов и пути к изображениям для OCR.
    """
    from app.services.pdf_converter import convert_pdf_to_images

    image_paths = []
    doc_texts = []
    for f in sorted(case.files, key=lambda x: (x.sort_order or 0)):
        path = Path(f.file_path)
        if not path.exists():
            continue
        ext = path.suffix.lower()

        if ext == ".pdf":
            pdf_text = await _extract_pdf_text(str(path))
            page_count = max(1, pdf_text.count(chr(12)) + 1) if pdf_text else 1
            chars_per_page = len(pdf_text.strip()) / page_count if pdf_text.strip() else 0
            if chars_per_page > 50:
                doc_texts.append(f"--- {f.filename} ---" + chr(10) + pdf_text.strip())
                logger.info(f"PDF {f.filename}: текст напрямую ({len(pdf_text)} симв) — $0")
            else:
                output_dir = path.parent / f"{path.stem}_pages"
                png_paths = await convert_pdf_to_images(str(path), str(output_dir))
                image_paths.extend(png_paths)
                logger.info(f"PDF {f.filename}: скан, OCR ({len(png_paths)} стр)")
        elif ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tiff", ".tif"):
            if ext in (".heic", ".heif"):
                from PIL import Image  # hoisted so except clause can reference it
                Image.MAX_IMAGE_PIXELS = 50_000_000
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                    jpeg_path = path.with_suffix(".jpg")
                    img = Image.open(path)
                    img.convert("RGB").save(jpeg_path, "JPEG", quality=92)
                    logger.info(f"Converted {f.filename} HEIC -> JPEG")
                    image_paths.append(str(jpeg_path))
                except Image.DecompressionBombError as e:
                    logger.error(f"HEIC rejected (decompression bomb) {f.filename}: {e}")
                except Exception as e:
                    logger.error(f"HEIC conversion failed {f.filename}: {e}")
                    image_paths.append(str(path))
            else:
                image_paths.append(str(path))
        elif ext == ".txt":
            try:
                tc = path.read_text(encoding="utf-8", errors="replace")
                if tc.strip():
                    doc_texts.append(f"--- {f.filename} ---\n{tc}")
            except Exception as e:
                logger.warning(f"Не удалось прочитать {f.filename}: {e}")
        elif ext == ".docx":
            try:
                from docx import Document as DocxDocument
                doc = DocxDocument(str(path))
                tc = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                if tc.strip():
                    doc_texts.append(f"--- {f.filename} ---\n{tc}")
            except Exception as e:
                logger.warning(f"Не удалось прочитать {f.filename}: {e}")
        elif ext == ".doc":
            try:
                import subprocess
                result = subprocess.run(
                    ["antiword", str(path)],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0 and result.stdout.strip():
                    doc_texts.append("--- " + f.filename + " ---" + chr(10) + result.stdout)
                else:
                    logger.warning(f"antiword не смог прочитать {f.filename}: {result.stderr}")
            except Exception as e:
                logger.warning(f"Не удалось прочитать .doc {f.filename}: {e}")
        elif ext in (".rtf", ".odt"):
            logger.info(f"Файл {f.filename} ({ext}) — не поддержан, пропускаем")

    return doc_texts, image_paths


def _auto_title_from_instructions(instructions: str) -> str:
    """Извлекает читаемое название документа из пользовательской инструкции.
    
    Убирает глаголы-паразиты и обрезает до 80 символов.
    Если инструкции нет — возвращает пустую строку.
    """
    if not instructions:
        return ""
    clean = instructions.strip()
    # Убираем глаголы в начале
    prefixes = [
        "напиши", "составь", "подготовь", "сделай", "проанализируй",
        "распиши", "сформируй", "вынеси", "подготовить", "составить",
    ]
    for p in prefixes:
        if clean.lower().startswith(p):
            clean = clean[len(p):].lstrip(" ,.-:;")
            break
    # Убираем "подробно", "развернуто", "пожалуйста" и т.п.
    clean = clean.strip()
    if not clean:
        return ""
    # Обрезаем до 80 символов, не разрывая слов
    if len(clean) > 80:
        clean = clean[:80].rsplit(" ", 1)[0]
    return clean


def _auto_title_from_text(generated_text: str) -> str:
    """Fallback: первые 80 символов текста если нет user_instructions."""
    if not generated_text:
        return ""
    clean = generated_text.strip()
    # Убираем заголовки-разделители
    clean = clean.lstrip("= \t\n\r")
    # Берём первую строку, обрезаем
    lines = clean.split("\n")
    for line in lines:
        line = line.strip()
        if line and len(line) > 20:
            clean = line[:80]
            break
    else:
        clean = clean[:80].rsplit(" ", 1)[0]
    return clean


async def run_pipeline_streaming(case_id: str, case: Case, db) -> dict:
    """
    Streaming pipeline: text -> DeepSeek chat_stream -> Redis chunks -> DB.
    No norm search — DeepSeek uses its own legal knowledge.
    """
    import time
    from app.services.redis_stream import publish_chunk, set_stream_status

    t0 = time.time()

    # ── Step 0: Extract text from files ──
    doc_texts, image_paths = await _extract_texts_from_files(case)

    if not image_paths and not doc_texts:
        raise ValueError("Нет загруженных файлов или не удалось обработать")

    combined_parts = list(doc_texts)

    # OCR for images
    ocr_page_count = 0
    if image_paths:
        from app.services.ocr import extract_text
        logger.info(f"OCR: {len(image_paths)} изображений")
        ocr_texts = await extract_text(image_paths)
        ocr_page_count = len(image_paths)
        for i, page_text in enumerate(ocr_texts):
            if page_text.strip():
                combined_parts.append(f"--- Страница {i + 1} ---\n{page_text}")

    if not combined_parts:
        raise ValueError("Не удалось извлечь текст ни из одного файла")

    combined_text = "\n\n".join(combined_parts)
    if len(combined_text) > MAX_OCR_TEXT_CHARS:
        combined_text = combined_text[:MAX_OCR_TEXT_CHARS] + "\n\n[Текст обрезан]"
        logger.warning(f"Текст обрезан до {MAX_OCR_TEXT_CHARS} символов")

    # Save OCR stats to case
    case.ocr_pages = ocr_page_count
    case.ocr_chars = len(combined_text)

    t_text = time.time()
    logger.info(f"Текст извлечён: {len(combined_text)} симв за {t_text - t0:.1f} сек, OCR страниц: {ocr_page_count}")

    # ── Step 1: Build prompt (NO norms) ──
    instructions_block = ""
    if case.user_instructions and case.user_instructions.strip():
        instructions_block = (
            f"\n\nУКАЗАНИЯ СУДЬИ (обязательно учти при составлении решения):\n"
            f"{case.user_instructions.strip()}\n"
        )

    messages = [
        {"role": "system", "content": PAID_PROMPT},
        {"role": "user", "content": (
            f"Материалы дела (текст извлечён из загруженных документов):\n\n"
            f"{combined_text}{instructions_block}\n\n"
            f"Напиши подробное мотивированное решение суда по делу. "
            f"Подробно раскрой позиции сторон и их аргументы."
        )},
    ]

    # ── Step 2: Stream from DeepSeek, publish chunks to Redis ──
    full_text_parts = []
    async for chunk in deepseek.chat_stream(messages, max_tokens=8192, temperature=0.3):
        full_text_parts.append(chunk)
        await publish_chunk(case_id, chunk)

    full_text = "".join(full_text_parts)

    # Убираем markdown-разметку (страховка)
    full_text = re.sub(r'\*\*(.+?)\*\*', r'\1', full_text)
    full_text = re.sub(r'__(.+?)__', r'\1', full_text)
    full_text = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'\1', full_text)
    full_text = re.sub(r'^#{1,6}\s+', '', full_text, flags=re.MULTILINE)

    t_ai = time.time()
    logger.info(f"DeepSeek stream: {len(full_text)} симв за {t_ai - t_text:.1f} сек")

    # ── Step 3: Save to DB ──
    case.generated_text = full_text
    case.final_text = full_text
    case.matched_norms = None
    case.validation_result = None
    case.fact_pack = {"source": "streaming_pipeline_v2"}
    case.status = "completed"

    # Auto-title
    if not case.title:
        auto = _auto_title_from_text(full_text)
        if auto:
            case.title = auto
            logger.info(f"Auto-title: {case.title}")

    # Token estimation (~3 chars per token for Russian)
    est_prompt_tokens = len(combined_text) // 3
    est_completion_tokens = len(full_text) // 3
    total = {"prompt_tokens": est_prompt_tokens, "completion_tokens": est_completion_tokens}
    case.tokens_used = total
    total_tokens = est_prompt_tokens + est_completion_tokens

    from app.config import get_settings
    _s = get_settings()
    # Cost = DeepSeek tokens + OCR pages. OCR was previously excluded, which
    # made admin revenue analytics show only ~0.2 RUB/case and triggered
    # the fallback estimator. Count images + (pdf_pages ≈ est_pages_per_pdf).
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

    # Notify Redis that stream is complete
    await set_stream_status(case_id, "completed")

    # Cleanup PNG
    import shutil
    def _cleanup():
        for f in case.files:
            p = Path(f.file_path)
            pages_dir = p.parent / f"{p.stem}_pages"
            if pages_dir.exists():
                shutil.rmtree(pages_dir, ignore_errors=True)
    await asyncio.to_thread(_cleanup)

    logger.info(f"Pipeline done in {time.time() - t0:.1f}s, {len(full_text)} chars, ~{total_tokens} tokens")

    # Фоновая валидация норм (AI-ревизор) — не блокирует пользователя
    from app.services.generate_from_context import _validate_norms_background
    asyncio.create_task(_validate_norms_background(case_id, full_text))

    return {"total_tokens": total_tokens, "usage": total}


# Legacy wrapper for backward compatibility
async def run_pipeline(case: Case, db) -> dict:
    """Non-streaming pipeline (legacy). Calls streaming version internally."""
    case_id = str(case.id)
    return await run_pipeline_streaming(case_id, case, db)
