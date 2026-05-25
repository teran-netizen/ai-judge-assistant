"""
Middleware безопасности уровня приложения.

Работает ДО роутинга — перехватывает ВСЕ запросы.
Три уровня защиты:

1. IP-бан: заблокированные IP сразу получают 403 (никакой обработки)
2. Глобальный rate limit: макс. запросов/сек с одного IP
3. Детекция подозрительных паттернов: автоматический бан при сканировании
"""

import time
import logging
import asyncio
import uuid as _uuid
from collections import defaultdict, deque
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ── Конфигурация ──

# Глобальный лимит: запросов с одного IP за окно
GLOBAL_RATE_LIMIT = 100        # запросов
GLOBAL_RATE_WINDOW = 10        # секунд (= 10 req/sec average)

# Автобан при превышении лимита N раз подряд
AUTOBAN_THRESHOLD = 5          # сколько раз IP словил 429 за окно
AUTOBAN_DURATION = 300         # бан на 5 минут

# Автобан при сканировании (много 404/444)
SCAN_THRESHOLD = 20            # 404-ответов за окно
SCAN_WINDOW = 60               # секунд
SCAN_BAN_DURATION = 600        # бан на 10 минут

# Макс. размер tracking-структур (защита от memory exhaustion)
MAX_TRACKED_IPS = 50_000

# Очистка каждые N секунд
CLEANUP_INTERVAL = 60


# Trusted proxy networks: only these sources may override client IP via
# X-Real-IP / X-Forwarded-For. Our app is only reachable via nginx inside
# Docker's bridge network (172.x); loopback kept for health probes from host.
import ipaddress as _ipaddr

_TRUSTED_PROXY_NETWORKS = [
    _ipaddr.ip_network("127.0.0.0/8"),
    _ipaddr.ip_network("::1/128"),
    _ipaddr.ip_network("10.0.0.0/8"),
    _ipaddr.ip_network("172.16.0.0/12"),
    _ipaddr.ip_network("192.168.0.0/16"),
]


def _is_trusted_proxy(ip: str) -> bool:
    if not ip:
        return False
    try:
        addr = _ipaddr.ip_address(ip)
        return any(addr in net for net in _TRUSTED_PROXY_NETWORKS)
    except (ValueError, TypeError):
        return False


def _get_ip(request: Request) -> str:
    """Возвращает IP клиента.

    Приоритет:
      1. Если прямой источник запроса — доверенный proxy (nginx во внутренней
         Docker-сети) → берём IP из X-Real-IP / X-Forwarded-For.
      2. Иначе (прямой запрос или неожиданный источник) → используем
         request.client.host. Это защищает rate-limiting от spoof-атак
         через подделку заголовков.
    """
    direct_ip = request.client.host if request.client else ""
    if _is_trusted_proxy(direct_ip):
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return direct_ip or "unknown"


class SecurityMiddleware(BaseHTTPMiddleware):
    """Глобальная защита на уровне приложения."""

    def __init__(self, app):
        super().__init__(app)

        # IP бан-лист: ip → unban_timestamp
        self._banned: dict[str, float] = {}

        # Rate limit counters: ip → deque of timestamps
        self._requests: dict[str, deque[float]] = defaultdict(deque)

        # 429 counter: ip → count (для автобана)
        self._rate_violations: dict[str, int] = defaultdict(int)

        # 404 counter: ip → deque of timestamps (для детекции сканирования)
        self._not_found: dict[str, deque[float]] = defaultdict(deque)

        # Whitelist (health checks only)
        self._whitelist_paths = frozenset({"/health"})

        self._last_cleanup = time.monotonic()
        self._lock = asyncio.Lock()

    def _cleanup(self, now: float):
        """Периодическая очистка устаревших записей."""
        if now - self._last_cleanup < CLEANUP_INTERVAL:
            return
        self._last_cleanup = now

        # Чистим баны
        expired = [ip for ip, t in self._banned.items() if now >= t]
        for ip in expired:
            del self._banned[ip]

        # Чистим counters
        cutoff = now - max(GLOBAL_RATE_WINDOW, SCAN_WINDOW) * 2
        for store in (self._requests, self._not_found):
            stale = [ip for ip, ts in store.items() if not ts or ts[-1] < cutoff]
            for ip in stale:
                del store[ip]

        # Чистим violations
        stale_v = [ip for ip, c in self._rate_violations.items() if c == 0]
        for ip in stale_v:
            del self._rate_violations[ip]

        # Защита от memory exhaustion
        for store in (self._requests, self._not_found):
            if len(store) > MAX_TRACKED_IPS:
                # Удаляем самые старые
                sorted_ips = sorted(store.items(), key=lambda x: x[1][-1] if x[1] else 0)
                for ip, _ in sorted_ips[:len(store) - MAX_TRACKED_IPS]:
                    del store[ip]

    def _is_banned(self, ip: str, now: float) -> bool:
        """Проверяет бан IP."""
        if ip not in self._banned:
            return False
        if now >= self._banned[ip]:
            del self._banned[ip]
            return False
        return True

    def _ban_ip(self, ip: str, duration: int, reason: str):
        """Банит IP на duration секунд."""
        now = time.monotonic()
        self._banned[ip] = now + duration
        logger.warning(f"IP BANNED: {ip} for {duration}s — {reason}")

        # Notify via telegram (async, fire-and-forget)
        try:
            asyncio.create_task(self._notify_ban(ip, duration, reason))
        except RuntimeError:
            pass  # no running event loop

    async def _notify_ban(self, ip: str, duration: int, reason: str):
        """Отправляет уведомление о бане в Telegram."""
        try:
            from app.services.telegram import send_admin
            import html as html_lib
            await send_admin(
                f"🛡 <b>IP забанен</b>\n"
                f"IP: <code>{html_lib.escape(ip)}</code>\n"
                f"Время: {duration} сек\n"
                f"Причина: {html_lib.escape(reason)}"
            )
        except Exception:
            pass

    def _check_rate_limit(self, ip: str, now: float) -> bool:
        """Глобальный rate limit. Returns True если разрешено."""
        timestamps = self._requests[ip]

        # Убираем старые записи
        cutoff = now - GLOBAL_RATE_WINDOW
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        if len(timestamps) >= GLOBAL_RATE_LIMIT:
            # Rate limit exceeded
            self._rate_violations[ip] += 1

            if self._rate_violations[ip] >= AUTOBAN_THRESHOLD:
                self._ban_ip(ip, AUTOBAN_DURATION, f"Rate limit exceeded {AUTOBAN_THRESHOLD}x")
                self._rate_violations[ip] = 0

            return False

        timestamps.append(now)
        return True

    def _track_not_found(self, ip: str, now: float):
        """Трекает 404 для детекции сканирования."""
        timestamps = self._not_found[ip]
        cutoff = now - SCAN_WINDOW
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        timestamps.append(now)

        if len(timestamps) >= SCAN_THRESHOLD:
            self._ban_ip(ip, SCAN_BAN_DURATION, f"Scanning detected: {len(timestamps)} 404s in {SCAN_WINDOW}s")
            self._not_found[ip].clear()

    async def dispatch(self, request: Request, call_next) -> Response:
        now = time.monotonic()
        self._cleanup(now)

        ip = _get_ip(request)
        path = request.url.path

        # ── 1. Health check bypass ──
        if path == "/health":
            return await call_next(request)

        # ── 2. Проверка бана ──
        if self._is_banned(ip, now):
            return JSONResponse(
                {"detail": "Доступ временно заблокирован"},
                status_code=403,
            )

        # ── 3. Глобальный rate limit ──
        if not self._check_rate_limit(ip, now):
            return JSONResponse(
                {"detail": "Слишком много запросов. Подождите несколько секунд."},
                status_code=429,
                headers={"Retry-After": str(GLOBAL_RATE_WINDOW)},
            )

        # ── 4. Выполнение запроса ──
        response = await call_next(request)

        # Telegram alert on 500 errors
        if response.status_code >= 500:
            try:
                from app.services.telegram import send_admin
                path = request.url.path
                await send_admin(f"{response.status_code} ошибка: {request.method} {path}")
            except: pass

        # ── 5. Request ID для трассировки и форензики ──
        request_id = _uuid.uuid4().hex[:16]
        response.headers["X-Request-ID"] = request_id

        # ── 6. Post-processing: трекаем 404 для scan detection ──
        if response.status_code == 404:
            self._track_not_found(ip, time.monotonic())

        # ── 7. Сброс violation counter при успешном запросе ──
        if response.status_code < 400 and ip in self._rate_violations:
            self._rate_violations[ip] = max(0, self._rate_violations[ip] - 1)

        return response
