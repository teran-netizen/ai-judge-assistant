from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Return datetime as timezone-aware UTC.

    Naive values are treated as UTC because the project historically stored naive
    UTC timestamps in the database. Aware values are converted to UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)

def utcnow_naive() -> datetime:
    """Timezone-naive current UTC time (для совместимости с БД-колонками timestamp without tz).

    Drop-in replacement для устаревшего datetime.utcnow().
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
