"""Secrets access. The env provider is for local work. Production should use a secrets manager behind the same interface."""
from __future__ import annotations

import os
from typing import Protocol

from packages.config import Settings

DEMO_SECRET_PREFIX = "demo-"


class SecretsProvider(Protocol):
    def get(self, name: str) -> str | None: ...


class EnvSecretsProvider:
    def get(self, name: str) -> str | None:
        return os.environ.get(name.upper())


def assert_production_secrets(settings: Settings) -> None:
    """Refuse to start in production with the demo signing key."""
    if settings.app_env.lower() == "production" and settings.jwt_secret_key.startswith(DEMO_SECRET_PREFIX):
        raise RuntimeError("JWT_SECRET_KEY is still the demo value. Set a real secret before you run in production.")
