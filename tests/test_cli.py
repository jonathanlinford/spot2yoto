"""Tests for CLI commands via Click test runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from spot2yoto.cli import cli


class TestHelpScreens:
    def test_main_help(self):
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "spot2yoto" in result.output

    def test_auth_help(self):
        result = CliRunner().invoke(cli, ["auth", "--help"])
        assert result.exit_code == 0
        assert "authentication" in result.output.lower()

    def test_cards_help(self):
        result = CliRunner().invoke(cli, ["cards", "--help"])
        assert result.exit_code == 0
        assert "cards" in result.output.lower()

    def test_config_help(self):
        result = CliRunner().invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        assert "config" in result.output.lower()

    def test_sync_help(self):
        result = CliRunner().invoke(cli, ["sync", "--help"])
        assert result.exit_code == 0
        assert "sync" in result.output.lower()

    def test_status_help(self):
        result = CliRunner().invoke(cli, ["status", "--help"])
        assert result.exit_code == 0


class TestConfigInit:
    def test_creates_config(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        result = CliRunner().invoke(
            cli, ["--config", str(config_path), "config", "init"]
        )
        assert result.exit_code == 0
        assert "Config created" in result.output
        assert config_path.exists()

    def test_already_exists(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("existing")
        result = CliRunner().invoke(
            cli, ["--config", str(config_path), "config", "init"]
        )
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestStatus:
    def test_no_history(self, tmp_path: Path):
        with patch("spot2yoto.cli.StateDB") as MockDB:
            mock_db = MagicMock()
            mock_db.get_all_card_states.return_value = []
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            MockDB.return_value = mock_db

            result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "No sync history" in result.output

    def test_with_history(self, tmp_path: Path):
        with patch("spot2yoto.cli.StateDB") as MockDB:
            mock_db = MagicMock()
            mock_db.get_all_card_states.return_value = [
                {
                    "mapping_name": "card-1",
                    "last_synced_at": "2024-01-01T00:00:00",
                    "playlist_snapshot_id": "snap123456789abc",
                },
            ]
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            MockDB.return_value = mock_db

            result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "card-1" in result.output
        assert "snap12345678" in result.output


class TestAuthStatus:
    def test_no_accounts(self):
        with patch("spot2yoto.cli.list_accounts", return_value=[]):
            with patch("spot2yoto.cli.load_config", side_effect=Exception("no config")):
                result = CliRunner().invoke(cli, ["auth", "status"])
        assert "not authenticated" in result.output

    def test_with_account(self, sample_tokens):
        with patch("spot2yoto.cli.list_accounts", return_value=["default"]):
            with patch("spot2yoto.cli.load_tokens", return_value=sample_tokens):
                with patch("spot2yoto.cli.load_config") as mock_cfg:
                    mock_cfg.return_value = MagicMock()
                    mock_cfg.return_value.spotify.client_id = "sid"
                    mock_cfg.return_value.spotify.client_secret = "sec"
                    result = CliRunner().invoke(cli, ["auth", "status"])
        assert "valid" in result.output


class TestSyncErrors:
    def test_no_config(self, tmp_path: Path):
        config_path = tmp_path / "nonexistent.yaml"
        result = CliRunner().invoke(
            cli, ["--config", str(config_path), "sync"]
        )
        assert result.exit_code != 0

    def test_no_accounts(self, tmp_config: Path):
        with patch("spot2yoto.cli.list_accounts", return_value=[]):
            result = CliRunner().invoke(
                cli, ["--config", str(tmp_config), "sync"]
            )
        assert result.exit_code != 0
        assert "No Yoto accounts" in result.output
