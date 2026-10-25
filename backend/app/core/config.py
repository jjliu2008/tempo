"""Typed application settings, read from environment / .env."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "API"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/app"
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    GOOGLE_API_KEY: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    GEMMA_MODEL: Literal["gemma-4-26b-a4b-it", "gemma-4-31b-it"] = "gemma-4-26b-a4b-it"
    GEMMA_TEMPERATURE: float = Field(default=0.7, ge=0, le=2, allow_inf_nan=False)
    GEMMA_MAX_OUTPUT_TOKENS: int = Field(default=2048, ge=1, le=32768)
    GEMMA_TIMEOUT_SECONDS: float = Field(default=60, gt=0, allow_inf_nan=False)
    GEMMA_MAX_CONCURRENT_REQUESTS: int = Field(default=4, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
