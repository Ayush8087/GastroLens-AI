import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(_env_file=None, cors_origins="https://example.test,http://localhost:3000")
    assert settings.cors_origins == ["https://example.test", "http://localhost:3000"]


def test_settings_reject_wildcard_cors_origin() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins="*")


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="staging")  # type: ignore[arg-type]
