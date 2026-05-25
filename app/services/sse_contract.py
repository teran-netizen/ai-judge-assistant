"""Strict SSE event contract for case streaming.

This module defines the allowed SSE event types and their payload schema.
It is used to:
1) Validate events before publishing them to Redis.
2) Parse/validate prefixed and legacy payloads when reading from Redis/pubsub.
"""
from __future__ import annotations

import json
from typing import Any, Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


EVENT_PREFIX = "__EVENT__:"
VALIDATION_PREFIX = "__VALIDATION__:"
DONE_MARKER = "__DONE__"
ERROR_PREFIX = "__ERROR__:"


class _StrictEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChunkEvent(_StrictEvent):
    type: Literal["chunk"]
    text: str


class FullEvent(_StrictEvent):
    type: Literal["full"]
    text: str


class DoneEvent(_StrictEvent):
    type: Literal["done"]


class ErrorEvent(_StrictEvent):
    type: Literal["error"]
    message: str
    error_code: str | None = None
    retryable: bool | None = None


class ValidationCompleteEvent(_StrictEvent):
    type: Literal["validation_complete"]
    stats: dict[str, Any]


class BatchDoneEvent(_StrictEvent):
    type: Literal["batch_done"]
    doc_count: int | None = None
    total_in_case: int | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    stage_label: str | None = None


class ProcessingEvent(_StrictEvent):
    type: Literal["processing"]
    filename: str
    index: int
    total: int
    progress_pct: int = Field(ge=0, le=100)
    stage_label: str


class OcrProgressEvent(_StrictEvent):
    type: Literal["ocr_progress"]
    message: str
    total_images: int
    completed_images: int
    progress_pct: int = Field(ge=0, le=100)
    stage_label: str


class OcrDoneEvent(_StrictEvent):
    type: Literal["ocr_done"]
    filename: str
    index: int
    total: int
    ocr_chars: int
    ocr_images: int
    ocr_elapsed: float
    progress_pct: int = Field(ge=0, le=100)
    stage_label: str


class DocDoneEvent(_StrictEvent):
    type: Literal["doc_done"]
    filename: str
    doc_type: str
    summary_line: str
    index: int
    total: int
    completed: int
    progress_pct: int = Field(ge=0, le=100)
    stage_label: str


class DocSkipEvent(_StrictEvent):
    type: Literal["doc_skip"]
    filename: str
    reason: str
    index: int
    total: int
    completed: int
    progress_pct: int = Field(ge=0, le=100)
    stage_label: str


class DocErrorEvent(_StrictEvent):
    type: Literal["doc_error"]
    filename: str
    error: str
    index: int
    total: int
    completed: int
    progress_pct: int = Field(ge=0, le=100)
    stage_label: str


class CompilingSummaryEvent(_StrictEvent):
    type: Literal["compiling_summary"]
    progress_pct: int = Field(ge=0, le=100)
    stage_label: str


SSEEvent = Annotated[
    Union[
        ChunkEvent,
        FullEvent,
        DoneEvent,
        ErrorEvent,
        ValidationCompleteEvent,
        BatchDoneEvent,
        ProcessingEvent,
        OcrProgressEvent,
        OcrDoneEvent,
        DocDoneEvent,
        DocSkipEvent,
        DocErrorEvent,
        CompilingSummaryEvent,
    ],
    Field(discriminator="type"),
]


_EVENT_ADAPTER = TypeAdapter(SSEEvent)
KNOWN_EVENT_TYPES = {
    "chunk",
    "full",
    "done",
    "error",
    "validation_complete",
    "batch_done",
    "processing",
    "ocr_progress",
    "ocr_done",
    "doc_done",
    "doc_skip",
    "doc_error",
    "compiling_summary",
}


def validate_sse_event(event: Any) -> dict[str, Any]:
    """Validate and normalize an SSE event payload."""
    validated = _EVENT_ADAPTER.validate_python(event)
    return validated.model_dump(exclude_none=True)


def is_known_event_type(event_type: str | None) -> bool:
    return bool(event_type) and event_type in KNOWN_EVENT_TYPES


def is_event_like_payload(raw: str) -> bool:
    """Return True when payload looks like an SSE envelope ({type: ...})."""
    if not isinstance(raw, str):
        return False
    raw = raw.strip()
    if not raw.startswith("{") or not raw.endswith("}"):
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and isinstance(data.get("type"), str)


def encode_event_payload(event: dict[str, Any]) -> str:
    """Encode a validated event payload with transport prefix for Redis."""
    normalized = validate_sse_event(event)
    return EVENT_PREFIX + json.dumps(normalized, ensure_ascii=False)


def decode_event_payload(raw: str) -> dict[str, Any] | None:
    """Decode SSE event payload from Redis/pubsub message.

    Supports:
    - Preferred prefixed format: "__EVENT__:{json}"
    - Validation payload format: "__VALIDATION__:{json}"
    - Legacy unprefixed JSON objects with known event type.
    Returns None when payload is not a recognized event.
    """
    if not isinstance(raw, str) or not raw:
        return None

    if raw.startswith(EVENT_PREFIX):
        payload = raw[len(EVENT_PREFIX):]
        data = json.loads(payload)
        return validate_sse_event(data)

    if raw.startswith(VALIDATION_PREFIX):
        payload = raw[len(VALIDATION_PREFIX):]
        data = json.loads(payload)
        return validate_sse_event(data)

    # Legacy fallback: raw JSON event (without prefix) from older workers.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    if not is_known_event_type(data.get("type")):
        return None
    return validate_sse_event(data)


def try_decode_event_payload(raw: str) -> dict[str, Any] | None:
    """Safe decode: never raises, returns None on invalid payload."""
    try:
        return decode_event_payload(raw)
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
        return None
