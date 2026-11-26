from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from packages.security.sanitizer import mask_text_pii

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    cid = correlation_id_var.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id_var.set(cid)
    return cid


class StructuredLogger:
    """Structured JSON logger that strips/masks PII and attaches correlation IDs."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

    def _emit(self, level: str, event: str, **fields: Any) -> None:
        safe_fields = {
            k: mask_text_pii(v) if isinstance(v, str) else v for k, v in fields.items()
        }
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
            "correlation_id": get_correlation_id(),
            **safe_fields,
        }
        getattr(self._logger, level.lower())(json.dumps(payload, default=str))

    def info(self, event: str, **fields: Any) -> None:
        self._emit("INFO", event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit("WARNING", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit("ERROR", event, **fields)
