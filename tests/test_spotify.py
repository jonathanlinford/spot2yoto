"""Tests for Spotify module (extract helpers and download)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from spot2yoto.exceptions import DownloadError, SpotifyError
from spot2yoto.spotify import _extract_playlist_id, _extract_track, download_track


class TestExtractPlaylistId:
    def test_standard_url(self):
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        assert _extract_playlist_id(url) == "37i9dQZF1DXcBWIGoYBM5M"

    def test_url_with_query_params(self):
        url = "https://open.spotify.com/playlist/abc123?si=xyz"
        assert _extract_playlist_id(url) == "abc123"

    def test_invalid_url(self):
        with pytest.raises(SpotifyError, match="Cannot extract"):
            _extract_playlist_id("https://example.com/notaplaylist")

    def test_partial_url(self):
        # Just the path portion
        assert _extract_playlist_id("playlist/ABC123def") == "ABC123def"


class TestExtractTrack:
    def test_item_format(self):
        entry = {"item": {"id": "t1", "name": "Track 1"}}
        result = _extract_track(entry)
        assert result["id"] == "t1"

    def test_track_format(self):
        entry = {"track": {"id": "t2", "name": "Track 2"}}
        result = _extract_track(entry)
        assert result["id"] == "t2"

    def test_item_takes_precedence(self):
        entry = {
            "item": {"id": "item-id", "name": "Item"},
            "track": {"id": "track-id", "name": "Track"},
        }
        result = _extract_track(entry)
        assert result["id"] == "item-id"

    def test_no_id_returns_none(self):
        entry = {"track": {"id": None, "name": "No ID"}}
        assert _extract_track(entry) is None

    def test_empty_entry(self):
        assert _extract_track({}) is None

    def test_missing_id_key(self):
        entry = {"track": {"name": "No ID field"}}
        assert _extract_track(entry) is None


class TestDownloadTrack:
    def test_cache_hit(self, tmp_path: Path):
        cached = tmp_path / "t1.mp3"
        cached.write_bytes(b"cached audio")
        result = download_track("Song", "Artist", tmp_path, "mp3", track_id="t1")
        assert result == cached

    def test_successful_download(self, tmp_path: Path):
        out_file = tmp_path / "t2.mp3"

        def fake_run(cmd, **kwargs):
            out_file.write_bytes(b"downloaded audio")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("spot2yoto.spotify.subprocess.run", side_effect=fake_run):
            result = download_track("Song", "Artist", tmp_path, "mp3", track_id="t2")
        assert result == out_file

    def test_download_failure(self, tmp_path: Path):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "error message")

        with patch("spot2yoto.spotify.subprocess.run", side_effect=fake_run):
            with pytest.raises(DownloadError, match="yt-dlp failed"):
                download_track("Song", "Artist", tmp_path, "mp3", track_id="t3")

    def test_no_track_id_uses_title_template(self, tmp_path: Path):
        out_file = tmp_path / "My Song.mp3"

        def fake_run(cmd, **kwargs):
            out_file.write_bytes(b"audio")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("spot2yoto.spotify.subprocess.run", side_effect=fake_run):
            result = download_track("My Song", "Artist", tmp_path, "mp3")
        assert result == out_file

    def test_search_query_format(self, tmp_path: Path):
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            (tmp_path / "t4.mp3").write_bytes(b"audio")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("spot2yoto.spotify.subprocess.run", side_effect=fake_run):
            download_track("Song Title", "Band Name", tmp_path, "mp3", track_id="t4")

        assert "ytsearch1:Band Name - Song Title" in captured_cmd
