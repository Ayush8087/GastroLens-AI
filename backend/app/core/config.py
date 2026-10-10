from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = (
        "postgresql+psycopg://restaurant_app:change-me@localhost:5432/restaurant_research"
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    tavily_api_key: SecretStr | None = None
    google_places_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    gemini_model: str = Field(default="gemini-3.8-flash", pattern=r"^gemini-[A-Za-z0-9.-]+$")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_production_cors(cls, origins: list[str], info: object) -> list[str]:
        # Wildcard origins with credentials are unsafe; production requires explicit origins.
        if "*" in origins:
            raise ValueError("CORS_ORIGINS must list explicit origins; wildcard is not allowed")
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
