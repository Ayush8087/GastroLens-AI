from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.routes.health import get_settings
from app.core.config import Settings
from app.main import app


def test_health_endpoint_reports_liveness() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_provider_health_reports_configuration_without_exposing_keys() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        google_places_api_key=SecretStr("google-secret"),
        tavily_api_key=None,
        gemini_api_key=SecretStr("gemini-secret"),
    )
    try:
        with TestClient(app) as client:
            response = client.get("/health/providers")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["live_checks_performed"] is False
    assert [item["configured"] for item in payload["providers"]] == [True, False, True]
    assert "google-secret" not in response.text
    assert "gemini-secret" not in response.text
