"""
Конфигурация проекта: загрузка переменных окружения из .env.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Telegram (нужны только для телеграм-бота, не для локального теста парсера) ---
    telegram_bot_token: str | None = None
    telegram_owner_id: int | None = None

    @field_validator("telegram_owner_id", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """Пустая строка в .env (незаполненная переменная) должна значить None, а не ошибку парсинга int."""
        if value == "":
            return None
        return value

    # --- Gemini ---
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite"

    # --- Kwork ---
    kwork_login: str | None = None
    kwork_password: str | None = None
    kwork_cookies: str | None = None

    # --- Anti-block ---
    parse_delay_min: float = 90
    parse_delay_max: float = 150
    proxy_list: str | None = None

    # --- Локальный тестовый веб-сервер парсера ---
    web_host: str = "127.0.0.1"
    web_port: int = 8000

    # --- Storage / logs ---
    db_path: str = "data/kwork_bot.db"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
