from __future__ import annotations

from typing import Any

from packages.config import get_settings


class ModelOutageError(Exception):
    """Raised when the configured LLM/vision provider is unavailable."""


class ModelGateway:
    """Provider-agnostic gateway supporting stub, Gemini, and Anthropic with outage fallback."""

    _runtime_outage_override: bool | None = None

    @classmethod
    def set_simulated_outage(cls, enabled: bool | None) -> None:
        cls._runtime_outage_override = enabled

    @classmethod
    def is_outage_active(cls) -> bool:
        if cls._runtime_outage_override is not None:
            return cls._runtime_outage_override
        return get_settings().ai_simulate_outage

    @classmethod
    def get_model_metadata(cls) -> tuple[str, str]:
        settings = get_settings()
        if settings.ai_provider_mode == "gemini":
            return ("gemini-2.5-flash", "2026-04")
        if settings.ai_provider_mode == "anthropic":
            return ("claude-sonnet-4", "2026-04")
        return ("motorclaim-deterministic-stub", "1.0.0")

    @classmethod
    def generate_structured_summary(cls, *, task: str, facts: dict[str, Any]) -> str:
        if cls.is_outage_active():
            raise ModelOutageError("Configured AI model gateway is currently unavailable (circuit open)")
        return f"[{task}] Processed {len(facts)} minimised claim context keys safely."
