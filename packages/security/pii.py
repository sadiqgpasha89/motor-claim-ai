"""PII redaction and rehydration. A model sees tokens. Only the caller holds the vault."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from services.rules_engine.security import security_controls

TOKEN_RE = re.compile(r"\[PII:([A-Z]+):(\d+)\]")


class PiiVault:
    """Maps tokens to original values for one request. Never store it, never log it."""

    def __init__(self) -> None:
        self._by_token: dict[str, str] = {}
        self._by_value: dict[str, str] = {}

    def token_for(self, kind: str, value: str) -> str:
        key = f"{kind}:{value}"
        if key in self._by_value:
            return self._by_value[key]
        token = f"[PII:{kind}:{len(self._by_token) + 1}]"
        self._by_token[token] = value
        self._by_value[key] = token
        return token

    def lookup(self, token: str) -> str | None:
        return self._by_token.get(token)

    def __len__(self) -> int:
        return len(self._by_token)


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    # Order matters: longer, more specific patterns first so an Aadhaar number is not read as an account number.
    order = ["EMAIL", "PAN", "AADHAAR", "PHONE", "ACCOUNT"]
    cfg = security_controls()["pii_patterns"]
    return [(k, re.compile(cfg[k])) for k in order if k in cfg]


def _replacer(kind: str, vault: PiiVault) -> Callable[[re.Match[str]], str]:
    return lambda m: vault.token_for(kind, m.group(0))


def redact_text(text: str, vault: PiiVault) -> str:
    for kind, pattern in _patterns():
        text = pattern.sub(_replacer(kind, vault), text)
    return text


def redact_value(value: Any, vault: PiiVault) -> Any:
    if isinstance(value, str):
        return redact_text(value, vault)
    if isinstance(value, dict):
        return {k: redact_value(v, vault) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v, vault) for v in value]
    return value


def rehydrate_text(text: str, vault: PiiVault) -> str:
    return TOKEN_RE.sub(lambda m: vault.lookup(m.group(0)) or m.group(0), text)


def contains_pii(text: str) -> bool:
    return any(p.search(text) for _, p in _patterns())
