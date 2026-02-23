"""Tests for ui module — render helpers, emoji constants, tables."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

import click

from spot2yoto import ui
from spot2yoto.ui import EMOJI, SyncStats


class TestEmojiConstants:
    def test_all_keys_present(self):
        expected = {
            "scan", "found", "sync", "check", "warn", "error",
            "download", "upload", "skip", "music", "card", "key",
            "art", "config", "party", "reuse", "dry", "trash",
        }
        assert expected == set(EMOJI.keys())

    def test_emoji_are_strings(self):
        for key, val in EMOJI.items():
            assert isinstance(val, str), f"EMOJI[{key}] should be str"
            assert len(val) >= 1, f"EMOJI[{key}] should not be empty"


class TestRenderMarkup:
    def test_plain_text_no_tty(self):
        with patch("spot2yoto.ui._use_color", return_value=False):
            result = ui._render_markup("[bold]hello[/bold]")
        assert "hello" in result
        # Should not contain ANSI escape codes
        assert "\x1b[" not in result

    def test_preserves_emoji_no_tty(self):
        with patch("spot2yoto.ui._use_color", return_value=False):
            result = ui._render_markup(f"{EMOJI['check']} done")
        assert EMOJI["check"] in result
        assert "done" in result


class TestOutputHelpers:
    """Test that output helpers emit text through click.echo (captured by CliRunner)."""

    def _capture(self, fn, *args, **kwargs):
        @click.command()
        def cmd():
            fn(*args, **kwargs)
        return CliRunner().invoke(cmd)

    def test_info(self):
        result = self._capture(ui.info, "hello world")
        assert "hello world" in result.output

    def test_success(self):
        result = self._capture(ui.success, "all good")
        assert "all good" in result.output
        assert EMOJI["check"] in result.output

    def test_warning(self):
        result = self._capture(ui.warning, "be careful")
        assert "be careful" in result.output
        assert EMOJI["warn"] in result.output

    def test_status_with_emoji(self):
        result = self._capture(ui.status, "downloading file", "download")
        assert "downloading file" in result.output
        assert EMOJI["download"] in result.output

    def test_status_no_emoji(self):
        result = self._capture(ui.status, "plain message")
        assert "plain message" in result.output

    def test_dim(self):
        result = self._capture(ui.dim, "verbose detail")
        assert "verbose detail" in result.output


class TestCardsTable:
    def test_renders_card_data(self):
        @click.command()
        def cmd():
            ui.cards_table([
                {"card_id": "abc-123", "title": "My Playlist", "has_spotify": True},
                {"card_id": "def-456", "title": "Chill Mix", "has_spotify": False},
            ])
        result = CliRunner().invoke(cmd)
        assert "abc-123" in result.output
        assert "My Playlist" in result.output
        assert "def-456" in result.output
        assert "Chill Mix" in result.output


class TestStatusTable:
    def test_renders_status_data(self):
        @click.command()
        def cmd():
            ui.status_table([
                {
                    "mapping_name": "card-1",
                    "last_synced_at": "2024-01-01T00:00:00",
                    "playlist_snapshot_id": "snap123456789abc",
                },
            ])
        result = CliRunner().invoke(cmd)
        assert "card-1" in result.output
        assert "2024-01-01T00:00:00" in result.output
        assert "snap12345678" in result.output


class TestAuthPanel:
    def test_renders_panel(self):
        @click.command()
        def cmd():
            ui.auth_panel("https://login.yoto.com/device", "ABCD-1234")
        result = CliRunner().invoke(cmd)
        assert "https://login.yoto.com/device" in result.output
        assert "ABCD-1234" in result.output


class TestSyncStats:
    def test_defaults(self):
        s = SyncStats()
        assert s.total_mappings == 0
        assert s.synced == 0
        assert s.failed == 0

    def test_accumulate(self):
        s = SyncStats(total_mappings=3)
        s.synced += 1
        s.downloaded += 5
        assert s.synced == 1
        assert s.downloaded == 5


class TestSyncSummary:
    def test_all_success(self):
        @click.command()
        def cmd():
            stats = SyncStats(total_mappings=3, synced=3, downloaded=5, uploaded=5, reused=2)
            ui.sync_summary(stats)
        result = CliRunner().invoke(cmd)
        assert "Sync Complete" in result.output
        assert "3 mapping(s) synced successfully" in result.output

    def test_with_failures(self):
        @click.command()
        def cmd():
            stats = SyncStats(total_mappings=3, synced=1, failed=2)
            ui.sync_summary(stats)
        result = CliRunner().invoke(cmd)
        assert "2/3 mapping(s) failed" in result.output
