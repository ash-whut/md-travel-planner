import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app

ENV_VARS = [name.upper() for name in Settings.model_fields]  # every variable Settings reads


@pytest.fixture
def default_settings(monkeypatch) -> Settings:
    """Settings with only the code defaults: ignores backend/.env and shell variables."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None)


@pytest.fixture
def client(default_settings):
    app.dependency_overrides[get_settings] = lambda: default_settings
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_settings_defaults_to_offline_mode(default_settings):
    assert default_settings.llm_provider == "fake"
    assert default_settings.tool_provider_mode == "mock"
    assert default_settings.database_url.endswith("backend/travel.db")


def test_health_returns_contract_shape(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "llm_provider": "fake", "tool_mode": "mock"}


def test_cors_allows_vite_dev_server(client):
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
