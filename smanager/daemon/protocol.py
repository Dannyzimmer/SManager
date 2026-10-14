"""Wire protocol for the SManager daemon.

Transport: newline-delimited JSON (NDJSON) over a local Unix domain socket.
One JSON object per line; strict parsing; bounded frame size.

Message kinds:

* request  ``{"id": <int>, "method": <str>, "params": {...}}``
* response ``{"id": <int>, "ok": true, "result": {...}}``
            ``{"id": <int>, "ok": false, "error": {"code", "message", "details"}}``
* event    ``{"id": <int>, "event": {...}}`` (streamed while an action runs)
"""

from __future__ import annotations

import json
from typing import Any, Optional


PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 1024 * 1024  # 1 MiB per message
DEFAULT_TIMEOUT = 30.0

# Error codes
ERR_BAD_REQUEST = "bad_request"
ERR_UNKNOWN_METHOD = "unknown_method"
ERR_NOT_FOUND = "not_found"
ERR_UNAUTHORIZED = "unauthorized"
ERR_PROTOCOL_MISMATCH = "protocol_mismatch"
ERR_TIMEOUT = "timeout"
ERR_UNSUPPORTED_ACTION = "unsupported_action"
ERR_INTERNAL = "internal"


class ProtocolError(Exception):
    """A structured error that can be sent back to the client."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_error(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def encode_message(message: dict[str, Any]) -> bytes:
    """Serialize a message to a single NDJSON frame."""
    data = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_FRAME_BYTES:
        raise ProtocolError(ERR_BAD_REQUEST, "message exceeds maximum frame size")
    return data + b"\n"


def decode_message(line: bytes) -> dict[str, Any]:
    """Parse a single NDJSON frame (without the trailing newline)."""
    try:
        obj = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(ERR_BAD_REQUEST, f"invalid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError(ERR_BAD_REQUEST, "message must be a JSON object")
    return obj


def make_request(request_id: int, method: str, params: Optional[dict] = None) -> dict[str, Any]:
    return {"id": request_id, "method": method, "params": params or {}}


def make_response(request_id: int, result: Any) -> dict[str, Any]:
    return {"id": request_id, "ok": True, "result": result}


def make_error(request_id: Optional[int], error: dict[str, Any]) -> dict[str, Any]:
    return {"id": request_id, "ok": False, "error": error}


def make_event(request_id: Optional[int], event: dict[str, Any]) -> dict[str, Any]:
    return {"id": request_id, "event": event}
