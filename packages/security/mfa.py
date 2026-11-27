"""TOTP (RFC 6238) for MFA step-up. Standard library only.

DEMO: the per-user secret is derived from the server secret. A real deployment keeps the secret in an
identity provider and uses OIDC `amr` claims. The step-up check in the API stays the same.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time

from packages.config import get_settings


def demo_secret_for(user_id: str) -> bytes:
    return hmac.new(get_settings().jwt_secret_key.encode(), f"mfa:{user_id}".encode(), hashlib.sha256).digest()[:20]


def totp(secret: bytes, *, at: float | None = None, period: int = 30, digits: int = 6) -> str:
    counter = int((time.time() if at is None else at) // period)
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def verify_totp(secret: bytes, code: str, *, at: float | None = None, period: int = 30, digits: int = 6, window: int = 1) -> bool:
    now = time.time() if at is None else at
    for step in range(-window, window + 1):
        if hmac.compare_digest(totp(secret, at=now + step * period, period=period, digits=digits), code):
            return True
    return False


def provisioning_secret_b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode()
