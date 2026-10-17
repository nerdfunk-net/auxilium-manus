"""S6-02: a production process never reads backend/.env."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import config


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", path)
    monkeypatch.delenv("ENABLE_DEV_TOOLS_PROBE", raising=False)
    return path


def test_production_image_ignores_backend_dotenv(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file.write_text("ENABLE_DEV_TOOLS_PROBE=true\n")
    monkeypatch.setenv("ENV", "production")
    config._load_dotenv_for_development()
    import os

    assert "ENABLE_DEV_TOOLS_PROBE" not in os.environ


def test_unset_env_without_file_value_counts_as_production(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file.write_text("ENABLE_DEV_TOOLS_PROBE=true\n")
    monkeypatch.delenv("ENV", raising=False)
    config._load_dotenv_for_development()
    import os

    assert "ENABLE_DEV_TOOLS_PROBE" not in os.environ


def test_development_loads_dotenv(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file.write_text("ENV=development\nENABLE_DEV_TOOLS_PROBE=true\n")
    monkeypatch.delenv("ENV", raising=False)
    config._load_dotenv_for_development()
    import os

    try:
        assert os.environ.get("ENABLE_DEV_TOOLS_PROBE") == "true"
    finally:
        os.environ.pop("ENABLE_DEV_TOOLS_PROBE", None)
        os.environ.pop("ENV", None)
