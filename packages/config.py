from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_name: str = "MotorClaim AI Intelligence Solution"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./motor_claim_ai.db"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = "demo-synthetic-dev-secret-change-in-prod-32chars"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    evidence_storage_dir: str = "./evidence_store"
    max_upload_size_mb: int = 25

    ai_provider_mode: str = "stub"  # stub | gemini | anthropic
    ai_simulate_outage: bool = False
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    integration_mode: str = "mock"  # mock | live

    @property
    def rules_dir(self) -> Path:
        return PROJECT_ROOT / "rules"

    @property
    def knowledge_dir(self) -> Path:
        return PROJECT_ROOT / "knowledge"


@lru_cache
def get_settings() -> Settings:
    return Settings()
