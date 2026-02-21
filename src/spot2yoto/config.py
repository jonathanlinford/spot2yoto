"""YAML config loading and validation."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from spot2yoto.exceptions import ConfigError
from spot2yoto.models import AppConfig

DEFAULT_CONFIG_DIR = Path("~/.config/spot2yoto").expanduser()
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"


def get_config_path(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    env = os.environ.get("SPOT2YOTO_CONFIG")
    if env:
        return Path(env).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or get_config_path()
    if not config_path.exists():
        raise ConfigError(
            f"Config file not found: {config_path}\n"
            "Run 'spot2yoto config init' to create one."
        )
    try:
        raw = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e
    return AppConfig.model_validate(raw)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    config_path = path or get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump(mode="json")
    config_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def create_default_config(path: Path | None = None) -> Path:
    config_path = path or get_config_path()
    if config_path.exists():
        raise ConfigError(f"Config already exists: {config_path}")
    config = AppConfig()
    save_config(config, config_path)
    return config_path
