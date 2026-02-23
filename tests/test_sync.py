"""Tests for sync orchestrator (compute_diff, discover_mappings, SPOTIFY_URL_RE)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spot2yoto.models import SpotifyTrack, YotoCard
from spot2yoto.state import StateDB
from spot2yoto.sync import SPOTIFY_URL_RE, Mapping, TrackDiff, compute_diff, discover_mappings


class TestSpotifyUrlRe:
    def test_matches_standard_url(self):
        text = "Check out https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        matches = SPOTIFY_URL_RE.findall(text)
        assert len(matches) == 1
        assert "37i9dQZF1DXcBWIGoYBM5M" in matches[0]

    def test_matches_url_with_query(self):
        text = "https://open.spotify.com/playlist/abc123?si=xyz"
        matches = SPOTIFY_URL_RE.findall(text)
        assert len(matches) == 1

    def test_no_match(self):
        text = "Just a normal description without spotify links"
        assert SPOTIFY_URL_RE.findall(text) == []

    def test_multiple_urls(self):
        text = (
            "Playlist 1: https://open.spotify.com/playlist/aaa\n"
            "Playlist 2: https://open.spotify.com/playlist/bbb"
        )
        matches = SPOTIFY_URL_RE.findall(text)
        assert len(matches) == 2

    def test_url_not_album(self):
        text = "https://open.spotify.com/album/abc123"
        assert SPOTIFY_URL_RE.findall(text) == []


class TestComputeDiff:
    def test_all_new(self, db: StateDB, sample_tracks: list[SpotifyTrack]):
        diff = compute_diff(sample_tracks, db, "card-1")
        assert len(diff.new_tracks) == 3
        assert diff.removed_track_ids == []
        assert diff.all_tracks == sample_tracks

    def test_no_changes(self, db: StateDB, sample_tracks: list[SpotifyTrack]):
        for t in sample_tracks:
            db.upsert_track(t.track_id, "card-1", t.position, "sha")
        diff = compute_diff(sample_tracks, db, "card-1")
        assert diff.new_tracks == []
        assert diff.removed_track_ids == []

    def test_removals(self, db: StateDB, sample_tracks: list[SpotifyTrack]):
        for t in sample_tracks:
            db.upsert_track(t.track_id, "card-1", t.position, "sha")
        # Only keep first track
        current = [sample_tracks[0]]
        diff = compute_diff(current, db, "card-1")
        assert diff.new_tracks == []
        assert set(diff.removed_track_ids) == {"t2", "t3"}

    def test_additions_and_removals(self, db: StateDB, sample_tracks: list[SpotifyTrack]):
        db.upsert_track("t1", "card-1", 0, "sha")
        db.upsert_track("old", "card-1", 1, "sha")
        diff = compute_diff(sample_tracks, db, "card-1")
        assert {t.track_id for t in diff.new_tracks} == {"t2", "t3"}
        assert diff.removed_track_ids == ["old"]


class TestDiscoverMappings:
    def test_finds_cards_with_spotify_urls(self):
        mock_yoto = MagicMock()
        mock_yoto.list_myo_cards.return_value = [
            YotoCard(
                card_id="c1",
                title="Card 1",
                description="https://open.spotify.com/playlist/abc123",
            ),
            YotoCard(card_id="c2", title="Card 2", description="No link here"),
        ]

        mock_sp = MagicMock()
        mock_sp.playlist.return_value = {"id": "abc123", "name": "Test Playlist"}

        mappings = discover_mappings(mock_yoto, mock_sp)
        assert len(mappings) == 1
        assert mappings[0].card.card_id == "c1"
        assert len(mappings[0].spotify_urls) == 1

    def test_no_cards(self):
        mock_yoto = MagicMock()
        mock_yoto.list_myo_cards.return_value = []
        mock_sp = MagicMock()

        mappings = discover_mappings(mock_yoto, mock_sp)
        assert mappings == []

    def test_skips_unreachable_playlist(self):
        mock_yoto = MagicMock()
        mock_yoto.list_myo_cards.return_value = [
            YotoCard(
                card_id="c1",
                title="Card 1",
                description="https://open.spotify.com/playlist/bad123",
            ),
        ]

        mock_sp = MagicMock()
        mock_sp.playlist.side_effect = Exception("not found")

        mappings = discover_mappings(mock_yoto, mock_sp)
        assert mappings == []

    def test_multiple_playlists_per_card(self):
        mock_yoto = MagicMock()
        mock_yoto.list_myo_cards.return_value = [
            YotoCard(
                card_id="c1",
                title="Multi",
                description=(
                    "https://open.spotify.com/playlist/aaa\n"
                    "https://open.spotify.com/playlist/bbb"
                ),
            ),
        ]

        mock_sp = MagicMock()
        mock_sp.playlist.return_value = {"id": "x", "name": "Playlist"}

        mappings = discover_mappings(mock_yoto, mock_sp)
        assert len(mappings) == 1
        assert len(mappings[0].spotify_urls) == 2

    def test_strips_query_params(self):
        mock_yoto = MagicMock()
        mock_yoto.list_myo_cards.return_value = [
            YotoCard(
                card_id="c1",
                title="Card",
                description="https://open.spotify.com/playlist/abc123?si=xyz&utm=123",
            ),
        ]

        mock_sp = MagicMock()
        mock_sp.playlist.return_value = {"id": "abc123", "name": "Test"}

        mappings = discover_mappings(mock_yoto, mock_sp)
        assert mappings[0].spotify_urls[0] == "https://open.spotify.com/playlist/abc123"
