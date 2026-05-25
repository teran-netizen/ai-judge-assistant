"""
OCR-сервис на базе Yandex Vision OCR API.

Два режима:
  1. Sync  (_recognize_single) — 1 RPS, ~2.3s/запрос. Legacy, для одиночных файлов.
  2. Async (_recognize_async_batch) — 10 RPS submit, параллельная обработка.
     3 шага: POST /recognizeTextAsync → poll /operations/{id} → GET /getRecognition

Async в 3-5x быстрее для пакетов: 10 изображений за ~5s вместо ~23s.

Цена: ~$1.30/1000 страниц. Поддержка: ru, en, автоопределение (48 языков).
"""
import asyncio
import base64
import logging
import time
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# ─── URLs ─────────────────────────────────────────────────────────────
YANDEX_OCR_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
YANDEX_OCR_ASYNC_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeTextAsync"
YANDEX_OCR_GET_RESULT_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/getRecognition"
YANDEX_OPERATION_URL = "https://operation.api.cloud.yandex.net/operations"

# ─── Async OCR settings ──────────────────────────────────────────────
# Submit rate limit: 10 RPS. Семафор ограничивает параллельные submit-ы.
ASYNC_SUBMIT_CONCURRENCY = 10
# Интервал поллинга операций (50 RPS limit, 0.5s — с запасом)
ASYNC_POLL_INTERVAL = 0.5
# Максимальное время ожидания одной операции
ASYNC_POLL_TIMEOUT = 60.0

# ─── Legacy sync settings ────────────────────────────────────────────
_RATE_LIMIT_DELAY = 1.1  # Yandex OCR sync limit: 1 req/sec

# Маппинг расширений → MIME-тип для Yandex API
_MIME_MAP = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".pdf": "PDF",
    ".webp": "PNG",
}


def _read_and_encode(image_path: str) -> tuple[str, str]:
    """Читает файл, возвращает (base64_content, mime_type)."""
    path = Path(image_path)
    ext = path.suffix.lower()
    mime_type = _MIME_MAP.get(ext, "JPEG")
    image_bytes = path.read_bytes()
    content_b64 = base64.b64encode(image_bytes).decode("utf-8")
    size_kb = len(image_bytes) / 1024
    logger.debug(f"OCR: {path.name} ({size_kb:.0f} КБ, {mime_type})")
    return content_b64, mime_type


def _extract_fulltext(data: dict) -> str:
    """Извлекает fullText из ответа Yandex OCR (sync или async getRecognition)."""
    # Путь 1: textAnnotation.fullText (getRecognition response)
    ta = data.get("textAnnotation")
    if ta:
        ft = ta.get("fullText", "")
        if ft:
            return ft.strip()

    # Путь 2: result.textAnnotation.fullText (sync response)
    result = data.get("result")
    if result and isinstance(result, dict):
        ta2 = result.get("textAnnotation", {})
        ft2 = ta2.get("fullText", "")
        if ft2:
            return ft2.strip()

    # Fallback: blocks → lines
    try:
        blocks_source = ta or (result or {}).get("textAnnotation", {})
        blocks = blocks_source.get("blocks", [])
        lines = []
        for block in blocks:
            for line in block.get("lines", []):
                text = line.get("text", "").strip()
                if text:
                    lines.append(text)
        if lines:
            return "\n".join(lines)
    except Exception:
        pass

    logger.warning("Yandex OCR: не удалось извлечь текст из ответа")
    return ""


# ═══════════════════════════════════════════════════════════════════════
# SYNC OCR (legacy — для одиночных файлов и обратной совместимости)
# ═══════════════════════════════════════════════════════════════════════

async def _recognize_single(
    client: httpx.AsyncClient,
    image_path: str,
    api_key: str,
) -> str:
    """Синхронный OCR — один запрос, ждёт результат. Rate limit: 1 RPS."""
    content_b64, mime_type = _read_and_encode(image_path)

    response = await client.post(
        YANDEX_OCR_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {api_key}",
        },
        json={
            "mimeType": mime_type,
            "languageCodes": ["ru", "en"],
            "model": "page",
            "content": content_b64,
        },
        timeout=30.0,
    )

    if response.status_code != 200:
        error_text = response.text[:500]
        logger.error(f"Yandex OCR sync ошибка {response.status_code}: {error_text}")
        response.raise_for_status()

    return _extract_fulltext(response.json())


# ═══════════════════════════════════════════════════════════════════════
# ASYNC OCR (для пакетной обработки — 10 RPS, параллельно)
# ═══════════════════════════════════════════════════════════════════════

async def _async_submit(
    client: httpx.AsyncClient,
    image_path: str,
    api_key: str,
) -> str | None:
    """
    Шаг 1: POST /recognizeTextAsync → operation_id.
    Возвращает operation_id или None при ошибке.
    """
    content_b64, mime_type = _read_and_encode(image_path)

    response = await client.post(
        YANDEX_OCR_ASYNC_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {api_key}",
        },
        json={
            "mimeType": mime_type,
            "languageCodes": ["ru", "en"],
            "model": "page",
            "content": content_b64,
        },
        timeout=30.0,
    )

    if response.status_code == 429:
        logger.warning(f"Yandex OCR async 429 (rate limit) для {image_path}, retrying with backoff")
        for _backoff in (2, 4, 8):
            await asyncio.sleep(_backoff)
            response = await client.post(
                YANDEX_OCR_SUBMIT_URL,
                headers={"Authorization": f"Api-Key {api_key}", "Content-Type": "application/json", "x-data-logging-enabled": "true"},
                json={"mimeType": mime, "languageCodes": ["ru", "en"], "model": "page", "content": content_b64},
                timeout=30.0,
            )
            if response.status_code != 429:
                break
        if response.status_code == 429:
            logger.error(f"Yandex OCR async 429 persistent для {image_path}")
            try:
                from app.services.telegram import send_admin
                asyncio.ensure_future(send_admin("OCR 429 persistent: " + str(image_path)[-30:]))
            except Exception:
                pass
            return None

    if response.status_code != 200:
        logger.error(f"Yandex OCR async ошибка {response.status_code}: {response.text[:300]}")
        return None

    data = response.json()
    op_id = data.get("id")
    if not op_id:
        logger.error(f"Yandex OCR async: нет operation_id в ответе")
        return None

    return op_id


async def _async_poll_done(
    client: httpx.AsyncClient,
    operation_id: str,
    api_key: str,
) -> bool:
    """
    Шаг 2: GET /operations/{id} → poll до done=true.
    Возвращает True если операция завершилась, False по таймауту.
    """
    start = time.monotonic()
    while time.monotonic() - start < ASYNC_POLL_TIMEOUT:
        response = await client.get(
            f"{YANDEX_OPERATION_URL}/{operation_id}",
            headers={"Authorization": f"Api-Key {api_key}"},
            timeout=10.0,
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("done"):
                return True
        else:
            logger.warning(f"OCR poll ошибка {response.status_code} для op={operation_id}")

        await asyncio.sleep(ASYNC_POLL_INTERVAL)

    logger.error(f"OCR async timeout для op={operation_id} ({ASYNC_POLL_TIMEOUT}s)")
    return False


async def _async_get_result(
    client: httpx.AsyncClient,
    operation_id: str,
    api_key: str,
) -> str:
    """
    Шаг 3: GET /getRecognition?operationId={id} → текст.
    """
    response = await client.get(
        YANDEX_OCR_GET_RESULT_URL,
        params={"operationId": operation_id},
        headers={"Authorization": f"Api-Key {api_key}"},
        timeout=30.0,
    )

    if response.status_code != 200:
        logger.error(f"OCR getRecognition ошибка {response.status_code}: {response.text[:300]}")
        return ""

    return _extract_fulltext(response.json())


async def _async_recognize_one(
    client: httpx.AsyncClient,
    image_path: str,
    api_key: str,
    submit_sem: asyncio.Semaphore,
    max_retries: int = 3,
) -> str:
    """
    Полный async OCR для одного изображения: submit → poll → get_result.
    submit_sem ограничивает параллельные submit-ы (10 RPS).
    Retry до max_retries раз при ошибках.
    """
    filename = Path(image_path).name

    for attempt in range(1, max_retries + 1):
        try:
            # Submit (с семафором для rate limit)
            async with submit_sem:
                op_id = await _async_submit(client, image_path, api_key)
            if not op_id:
                if attempt < max_retries:
                    logger.info(f"OCR retry {attempt}/{max_retries} submit failed: {filename}")
                    await asyncio.sleep(3 * attempt)
                    continue
                logger.warning(f"OCR async: не удалось отправить {filename} после {max_retries} попыток")
                return ""

            # Poll
            done = await _async_poll_done(client, op_id, api_key)
            if not done:
                if attempt < max_retries:
                    logger.info(f"OCR retry {attempt}/{max_retries} poll failed: {filename}")
                    await asyncio.sleep(3 * attempt)
                    continue
                logger.warning(f"OCR async: poll не завершился для {filename}")
                return ""

            # Get result
            text = await _async_get_result(client, op_id, api_key)
            if text.strip():
                logger.debug(f"OCR async {filename}: {len(text)} символов (attempt {attempt})")
                return text
            elif attempt < max_retries:
                logger.info(f"OCR retry {attempt}/{max_retries} empty result: {filename}")
                await asyncio.sleep(3 * attempt)
                continue
            else:
                logger.warning(f"OCR async: пустой результат для {filename} после {max_retries} попыток")
                return ""
        except Exception as e:
            if attempt < max_retries:
                logger.info(f"OCR retry {attempt}/{max_retries} error: {filename}: {e}")
                await asyncio.sleep(3 * attempt)
            else:
                logger.warning(f"OCR async error {filename} после {max_retries} попыток: {e}")
                return ""

    return ""


async def recognize_async_batch(
    image_paths: list[str],
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
    on_single_done: callable = None,
) -> list[str]:
    """
    Пакетный async OCR: все изображения обрабатываются параллельно.

    10 RPS submit → параллельная обработка на стороне Yandex → получение результатов.
    10 изображений за ~5s вместо ~23s (sync).

    Args:
        image_paths: Пути к изображениям.
        client: httpx.AsyncClient (опционально, создаст свой если не передан).
        api_key: API ключ (опционально, возьмёт из settings).
        on_single_done: callback(index, text) вызывается когда одно изображение готово.

    Returns:
        Список текстов в том же порядке, что и image_paths.
    """
    if not image_paths:
        return []

    if not api_key:
        settings = get_settings()
        api_key = settings.yandex_ocr_api_key
    if not api_key:
        logger.error("YANDEX_OCR_API_KEY не задан!")
        return [""] * len(image_paths)

    submit_sem = asyncio.Semaphore(ASYNC_SUBMIT_CONCURRENCY)

    async def _do_one(idx: int, path: str) -> tuple[int, str]:
        text = await _async_recognize_one(client_to_use, path, api_key, submit_sem)
        if on_single_done:
            await on_single_done(idx, text) if asyncio.iscoroutinefunction(on_single_done) else on_single_done(idx, text)
        return idx, text

    own_client = client is None
    client_to_use = client or httpx.AsyncClient(timeout=60.0)

    try:
        t0 = time.monotonic()
        results = [""] * len(image_paths)
        ok_count = 0
        BATCH_SIZE = 10  # Process 10 images at a time to avoid rate limits

        all_items = list(enumerate(image_paths))
        for batch_start in range(0, len(all_items), BATCH_SIZE):
            batch = all_items[batch_start:batch_start + BATCH_SIZE]
            batch_tasks = [_do_one(idx, path) for idx, path in batch]
            raw_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            for item in raw_results:
                if isinstance(item, Exception):
                    logger.warning(f"OCR async exception: {item}")
                    continue
                idx, text = item
                results[idx] = text
                if text.strip():
                    ok_count += 1

            # Pause between batches to respect rate limits
            if batch_start + BATCH_SIZE < len(all_items):
                await asyncio.sleep(1.5)

        elapsed = time.monotonic() - t0
        total_chars = sum(len(t) for t in results)
        logger.info(
            f"OCR async batch: {ok_count}/{len(image_paths)} страниц за {elapsed:.1f}s, "
            f"{total_chars} символов (batches of {BATCH_SIZE})"
        )
        return results

    finally:
        if own_client:
            await client_to_use.aclose()


# ═══════════════════════════════════════════════════════════════════════
# Legacy API (для обратной совместимости)
# ═══════════════════════════════════════════════════════════════════════

async def extract_text(image_paths: list[str]) -> list[str]:
    """
    Legacy: последовательный sync OCR.
    Для нового кода используйте recognize_async_batch().
    """
    if not image_paths:
        return []

    settings = get_settings()
    api_key = settings.yandex_ocr_api_key

    if not api_key:
        logger.error("YANDEX_OCR_API_KEY не задан!")
        return [""] * len(image_paths)

    valid_entries = []
    for i, p in enumerate(image_paths):
        path = Path(p)
        if path.exists() and path.stat().st_size > 0:
            valid_entries.append((i, str(path)))
        else:
            logger.warning(f"OCR: файл не найден или пуст: {p}")

    if not valid_entries:
        return [""] * len(image_paths)

    logger.info(f"OCR sync: распознаю {len(valid_entries)} изображений...")

    results = [""] * len(image_paths)

    async with httpx.AsyncClient() as client:
        for idx, (orig_idx, img_path) in enumerate(valid_entries):
            try:
                text = await _recognize_single(client, img_path, api_key)
                results[orig_idx] = text
            except Exception as e:
                logger.warning(f"OCR ошибка на изображении {orig_idx + 1}: {e}")

            if idx < len(valid_entries) - 1:
                await asyncio.sleep(_RATE_LIMIT_DELAY)

    total_chars = sum(len(t) for t in results)
    non_empty = sum(1 for t in results if t.strip())
    logger.info(f"OCR sync завершён: {non_empty}/{len(valid_entries)} страниц, {total_chars} символов")
    return results
