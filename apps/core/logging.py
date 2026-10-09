"""Structured JSON logs with sensitive values scrubbed (spec sections 16, 19)."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from .context import get_request_id

_SENSITIVE_KEY_PARTS = ("password", "token", "secret", "otp", "authorization", "cookie")
_SENSITIVE_KEYS = {"phone", "email", "code_hash"}
_PHONE = re.compile(r"(?<!\d)(?:\+?234|0)[789][01]\d{8}(?!\d)")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
REDACTED = "[redacted]"


def mask_text(text: str) -> str:
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    return _PHONE.sub(lambda m: "*" * (len(m.group()) - 3) + m.group()[-3:], text)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SENSITIVE_KEYS or any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED if _is_sensitive(str(k)) else scrub(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return mask_text(value)
    return value


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    _RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
        "message",
        "asctime",
        "request_id",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": mask_text(record.getMessage()),
            "request_id": getattr(record, "request_id", ""),
        }
        extras = {k: v for k, v in vars(record).items() if k not in self._RESERVED}
        if extras:
            payload["extra"] = scrub(extras)
        if record.exc_info:
            payload["exc"] = mask_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)
