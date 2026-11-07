"""Settings: reads backend/.env-style files, env vars win, tests run offline."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import ENV_FILE, Settings, get_settings


def test_conftest_forces_offline_env_vars() -> None:
    assert os.environ["LLM_PROVIDER"] == "fake"
    assert os.environ["TOOL_PROVIDER_MODE"] == "mock"


def test_get_settings_is_offline_in_tests() -> None:
    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.llm_provider == "fake"
    assert settings.tool_provider_mode == "mock"


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_settings_fixture_is_offline(settings: Settings) -> None:
    assert settings.llm_provider == "fake"
    assert settings.tool_provider_mode == "mock"


def test_defaults_are_safe_offline_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TOOL_PROVIDER_MODE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "fake"
    assert settings.tool_provider_mode == "mock"
    assert settings.database_url is None


def test_env_file_points_at_backend_dir() -> None:
    assert ENV_FILE.name == ".env"
    assert ENV_FILE.parent.name == "backend"
    assert (ENV_FILE.parent / "app" / "main.py").is_file()


def test_reads_values_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TOOL_PROVIDER_MODE", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=openai_compat\n"
        "LLM_MODEL=some-model\n"
        "TOOL_PROVIDER_MODE=live\n"
        "GEOAPIFY_KEY=geo-key\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.llm_provider == "openai_compat"
    assert settings.llm_model == "some-model"
    assert settings.tool_provider_mode == "live"
    assert settings.geoapify_key == "geo-key"


def test_env_vars_win_over_env_file(tmp_path: Path) -> None:
    # conftest has set LLM_PROVIDER=fake and TOOL_PROVIDER_MODE=mock in the environment.
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=openai_compat\nTOOL_PROVIDER_MODE=live\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.llm_provider == "fake"
    assert settings.tool_provider_mode == "mock"


def test_unknown_keys_in_env_file_are_ignored(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GOOGLE_MAPS_KEY=old-stale-key\nSOMETHING_ELSE=1\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.llm_provider == "fake"


def test_env_example_loads_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TOOL_PROVIDER_MODE", raising=False)

    settings = Settings(_env_file=ENV_FILE.parent / ".env.example")

    assert settings.llm_provider == "fake"
    assert settings.tool_provider_mode == "mock"


@pytest.mark.parametrize(
    "field, value",
    [("llm_provider", "anthropic"), ("tool_provider_mode", "sometimes")],
)
def test_invalid_modes_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_live_marker_is_registered_and_skipped_by_default(request: pytest.FixtureRequest) -> None:
    markers = request.config.getini("markers")
    assert any(m.startswith("live:") for m in markers)
    assert request.config.option.markexpr == "not live"
