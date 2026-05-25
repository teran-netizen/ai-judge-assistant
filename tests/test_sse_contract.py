import json

import pytest
from pydantic import ValidationError

from app.services.sse_contract import (
    EVENT_PREFIX,
    VALIDATION_PREFIX,
    decode_event_payload,
    encode_event_payload,
    is_event_like_payload,
    try_decode_event_payload,
    validate_sse_event,
)


def test_validate_sse_event_accepts_known_payload() -> None:
    payload = {
        "type": "processing",
        "filename": "file.jpg",
        "index": 0,
        "total": 2,
        "progress_pct": 10,
        "stage_label": "OCR",
    }
    result = validate_sse_event(payload)
    assert result == payload


def test_validate_sse_event_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        validate_sse_event({"type": "unknown", "foo": "bar"})


def test_decode_prefixed_event_payload() -> None:
    raw = encode_event_payload({"type": "batch_done", "stage_label": "Done"})
    assert raw.startswith(EVENT_PREFIX)
    decoded = decode_event_payload(raw)
    assert decoded == {"type": "batch_done", "stage_label": "Done"}


def test_decode_validation_prefix_payload() -> None:
    payload = {"type": "validation_complete", "stats": {"total": 3, "found": 2, "not_found": 1}}
    raw = f"{VALIDATION_PREFIX}{json.dumps(payload)}"
    decoded = decode_event_payload(raw)
    assert decoded == payload


def test_decode_legacy_json_event_payload() -> None:
    raw = json.dumps({"type": "ocr_progress", "message": "step", "total_images": 2, "completed_images": 1, "progress_pct": 50, "stage_label": "OCR"})
    decoded = decode_event_payload(raw)
    assert decoded["type"] == "ocr_progress"
    assert decoded["progress_pct"] == 50


def test_try_decode_returns_none_for_non_events() -> None:
    assert try_decode_event_payload("plain text chunk") is None
    assert try_decode_event_payload("{bad json") is None
    assert try_decode_event_payload(json.dumps({"type": "not_contract"})) is None


def test_is_event_like_payload_detects_envelopes() -> None:
    assert is_event_like_payload(json.dumps({"type": "processing", "filename": "f", "index": 0, "total": 1, "progress_pct": 10, "stage_label": "OCR"}))
    assert is_event_like_payload(json.dumps({"type": "unknown"}))
    assert not is_event_like_payload("plain text")
    assert not is_event_like_payload(json.dumps({"hello": "world"}))
