"""Shared fixtures for spot2yoto tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from spot2yoto.models import (
    AppConfig,
    SpotifyTrack,
    TokenData,
    YotoCard,
)
from spot2yoto.state import StateDB


@pytest.fixture
def db(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "test.db")


@pytest.fixture
def sample_tokens() -> TokenData:
    return TokenData(
        access_token="test-access",
        refresh_token="test-refresh",
        token_type="Bearer",
        expires_at=time.time() + 3600,
    )


@pytest.fixture
def expired_tokens() -> TokenData:
    return TokenData(
        access_token="old-access",
        refresh_token="old-refresh",
        token_type="Bearer",
        expires_at=0.0,
    )


@pytest.fixture
def sample_tracks() -> list[SpotifyTrack]:
    return [
        SpotifyTrack(
            track_id="t1",
            name="Song One",
            artist="Artist A",
            duration_ms=180000,
            spotify_url="https://open.spotify.com/track/t1",
            position=0,
            album_image_url="https://example.com/img1.jpg",
        ),
        SpotifyTrack(
            track_id="t2",
            name="Song Two",
            artist="Artist B",
            duration_ms=240000,
            spotify_url="https://open.spotify.com/track/t2",
            position=1,
            album_image_url="https://example.com/img2.jpg",
        ),
        SpotifyTrack(
            track_id="t3",
            name="Song Three",
            artist="Artist C",
            duration_ms=200000,
            spotify_url="https://open.spotify.com/track/t3",
            position=2,
        ),
    ]


@pytest.fixture
def sample_card() -> YotoCard:
    return YotoCard(
        card_id="card-123",
        title="My Playlist",
        description="https://open.spotify.com/playlist/abc123",
    )


@pytest.fixture
def mp3_file(tmp_path: Path) -> Path:
    p = tmp_path / "test.mp3"
    p.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1000)
    return p


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "yoto:\n  client_id: test-yoto-id\n"
        "spotify:\n  client_id: test-spotify-id\n  client_secret: test-secret\n"
    )
    return config_path


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig()
