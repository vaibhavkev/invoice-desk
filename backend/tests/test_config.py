"""backend/.env loading (SPEC 1)."""
from __future__ import annotations

from app import config


def _env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("EXTRACTION_EFFORT=from-file\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env)
    return tmp_path / "no-config.yaml"


def test_env_file_is_loaded(tmp_path, monkeypatch):
    missing = _env_file(tmp_path, monkeypatch)
    monkeypatch.setenv("EXTRACTION_EFFORT", "")  # registers the undo for what load_dotenv sets
    monkeypatch.delenv("EXTRACTION_EFFORT")
    assert config.load_settings(missing).extraction.effort == "from-file"


def test_real_environment_wins_over_env_file(tmp_path, monkeypatch):
    missing = _env_file(tmp_path, monkeypatch)
    monkeypatch.setenv("EXTRACTION_EFFORT", "from-shell")
    assert config.load_settings(missing).extraction.effort == "from-shell"


def test_missing_env_file_is_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "nope.env")
    assert config.load_settings(tmp_path / "no-config.yaml").port > 0
