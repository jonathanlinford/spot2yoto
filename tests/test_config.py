"""Tests for config loading, saving, and creation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from spot2yoto.config import (
    create_default_config,
    get_config_path,
    load_config,
    save_config,
)
from spot2yoto.exceptions import ConfigError
from spot2yoto.models import AppConfig


class TestGetConfigPath:
    def test_override(self):
        p = get_config_path("/tmp/custom.yaml")
        assert p == Path("/tmp/custom.yaml")

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SPOT2YOTO_CONFIG", "/tmp/env.yaml")
        p = get_config_path()
        assert p == Path("/tmp/env.yaml")

    def test_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SPOT2YOTO_CONFIG", raising=False)
        p = get_config_path()
        assert p == Path("~/.config/spot2yoto/config.yaml").expanduser()

    def test_override_takes_precedence_over_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SPOT2YOTO_CONFIG", "/tmp/env.yaml")
        p = get_config_path("/tmp/override.yaml")
        assert p == Path("/tmp/override.yaml")

    def test_tilde_expansion(self):
        p = get_config_path("~/myconfig.yaml")
        assert "~" not in str(p)


class TestLoadConfig:
    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(ConfigError, match="Config file not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml(self, tmp_path: Path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(": : : invalid")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_config(bad)

    def test_empty_file(self, tmp_path: Path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        cfg = load_config(empty)
        assert isinstance(cfg, AppConfig)
        assert cfg.yoto.client_id == ""

    def test_valid_file(self, tmp_config: Path):
        cfg = load_config(tmp_config)
        assert cfg.yoto.client_id == "test-yoto-id"
        assert cfg.spotify.client_id == "test-spotify-id"


class TestSaveConfig:
    def test_save_and_reload(self, tmp_path: Path):
        cfg = AppConfig.model_validate({
            "yoto": {"client_id": "saved-id"},
        })
        path = tmp_path / "out.yaml"
        save_config(cfg, path)
        loaded = load_config(path)
        assert loaded.yoto.client_id == "saved-id"

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "sub" / "dir" / "config.yaml"
        save_config(AppConfig(), path)
        assert path.exists()


class TestCreateDefaultConfig:
    def test_creates_config(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        result = create_default_config(path)
        assert result == path
        assert path.exists()
        cfg = load_config(path)
        assert isinstance(cfg, AppConfig)

    def test_raises_if_exists(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text("existing")
        with pytest.raises(ConfigError, match="already exists"):
            create_default_config(path)
