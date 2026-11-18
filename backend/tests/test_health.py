from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app

FRONTEND_ORIGIN = "http://localhost:5173"


def test_health_reports_offline_modes(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "llm_provider": "fake", "tool_mode": "mock"}


def test_health_is_served_under_api_prefix_only(client: TestClient) -> None:
    assert client.get("/health").status_code == 404


def test_health_reflects_the_configured_modes() -> None:
    app = create_app()
    live = Settings(_env_file=None, llm_provider="openai_compat", tool_provider_mode="live")
    app.dependency_overrides[get_settings] = lambda: live

    body = TestClient(app).get("/api/health").json()

    assert body == {"ok": True, "llm_provider": "openai_compat", "tool_mode": "live"}


def test_health_without_overrides_uses_forced_offline_env() -> None:
    # conftest sets LLM_PROVIDER/TOOL_PROVIDER_MODE, which win over any local backend/.env.
    get_settings.cache_clear()
    try:
        body = TestClient(create_app()).get("/api/health").json()
    finally:
        get_settings.cache_clear()

    assert body["llm_provider"] == "fake"
    assert body["tool_mode"] == "mock"


def test_cors_allows_the_frontend_dev_origin(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_cors_header_on_simple_get_from_frontend(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Origin": FRONTEND_ORIGIN})

    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_cors_rejects_other_origins(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers
