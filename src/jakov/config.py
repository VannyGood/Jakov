"""Application settings loaded from environment variables and `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: SecretStr
    admin_ids: Annotated[list[int], NoDecode] = Field(min_length=1)
    timezone: str = "UTC"

    database_url: str = f"sqlite+aiosqlite:///{PROJECT_ROOT / 'var' / 'jakov.db'}"
    var_dir: Path = PROJECT_ROOT / "var"
    data_dir: Path = PROJECT_ROOT / "data"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False

    run_mode: Literal["polling", "webhook"] = "polling"
    webhook_base_url: str | None = None
    webhook_path: str = "/telegram"
    webhook_secret: SecretStr | None = None
    webhook_host: str = "0.0.0.0"  # noqa: S104 - container default, configurable
    webhook_port: int = 8080

    emoji_test_pack: str = "RestrictedEmoji"
    health_log_interval_s: int = 600

    # Local AI writer (Ollama). Templates are the automatic backup when it's unavailable.
    llm_enabled: bool = True
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:1b"
    llm_timeout_s: float = Field(default=120.0, ge=5.0, le=600.0)
    llm_temperature: float = Field(default=0.9, ge=0.0, le=2.0)

    # Scheduler
    scheduler_tick_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    # A run more than this many minutes late (e.g. bot was offline) is skipped and logged.
    catchup_grace_minutes: int = Field(default=15, ge=0, le=24 * 60)
    approval_timeout_minutes: int = Field(default=30, ge=1, le=7 * 24 * 60)
    min_interval_minutes: int = Field(default=5, ge=1)

    virustotal_api_key: SecretStr | None = None
    safe_browsing_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            parts = [p.strip() for p in value.replace(";", ",").split(",")]
            return [int(p) for p in parts if p]
        return value

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"Unknown timezone {value!r}; use an IANA name like Europe/Berlin"
            ) from exc
        return value

    @field_validator("virustotal_api_key", "safe_browsing_api_key", "anthropic_api_key",
                     "webhook_secret", mode="before")
    @classmethod
    def _empty_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _check_webhook(self) -> Settings:
        if self.run_mode == "webhook" and not self.webhook_base_url:
            raise ValueError("RUN_MODE=webhook requires WEBHOOK_BASE_URL")
        return self

    @property
    def primary_owner_id(self) -> int:
        """Workspace owner. Single-tenant for now: every row belongs to the first admin."""
        return self.admin_ids[0]

    @property
    def default_zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def secret_values(self) -> list[str]:
        secrets = [self.bot_token, self.virustotal_api_key, self.safe_browsing_api_key,
                   self.anthropic_api_key, self.webhook_secret]
        return [s.get_secret_value() for s in secrets if s is not None and s.get_secret_value()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
