"""
Конвертация PDF → PNG для анализа через DeepSeek Vision.
Использует pdf2image (poppler/pdftoppm).
"""

import logging
import asyncio
from pathlib import Path
from pdf2image import convert_from_path

logger = logging.getLogger(__name__)

# Качество конвертации: 120 DPI — достаточно для Yandex OCR (рекомендация ≥100 DPI),
# ~35% быстрее конвертация и меньше размер PNG по сравнению с 150 DPI
PDF_DPI = 120
MAX_PAGES_PER_PDF = 50  # защита от 500-страничных PDF
MAX_PDF_FILE_SIZE = 100 * 1024 * 1024  # 100 MB — макс размер PDF
PDF_CONVERSION_TIMEOUT = 300  # секунд на конвертацию одного PDF


def _convert_sync(pdf_path: str, output_dir: str) -> list[str]:
    """
    Синхронная конвертация PDF → PNG.
    Возвращает список путей к PNG-файлам.
    """
    path = Path(pdf_path)
    if not path.exists():
        return []

    # Защита от гигантских PDF
    file_size = path.stat().st_size
    if file_size > MAX_PDF_FILE_SIZE:
        logger.warning(f"PDF too large ({file_size} bytes), skipping: {pdf_path}")
        return []

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        images = convert_from_path(
            str(path),
            dpi=PDF_DPI,
            first_page=1,
            last_page=MAX_PAGES_PER_PDF,
            fmt="png",
            size=(1600, None),  # 1600px достаточно для OCR, быстрее конвертация
        )
    except Exception as e:
        logger.error(f"PDF conversion failed for {pdf_path}: {e}")
        return []

    result = []
    for i, img in enumerate(images):
        png_path = out / f"{path.stem}_page_{i + 1:03d}.png"
        img.save(str(png_path), "PNG")
        result.append(str(png_path))

    logger.info(f"Converted {path.name}: {len(result)} pages")
    return result


async def convert_pdf_to_images(pdf_path: str, output_dir: str) -> list[str]:
    """Async wrapper — запускает конвертацию в thread pool с таймаутом."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_convert_sync, pdf_path, output_dir),
            timeout=PDF_CONVERSION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error(f"PDF conversion timed out after {PDF_CONVERSION_TIMEOUT}s: {pdf_path}")
        return []
