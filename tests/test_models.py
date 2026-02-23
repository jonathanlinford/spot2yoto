"""Tests for Pydantic models."""

from __future__ import annotations

import time

from spot2yoto.models import (
    AppConfig,
    DownloadConfig,
    SpotifyConfig,
    SpotifyPlaylist,
    SpotifyTrack,
    SyncConfig,
    TokenData,
    YotoCard,
    YotoChapter,
    YotoConfig,
    YotoContentPayload,
    YotoTranscodeResult,
    YotoUploadUrl,
)


class TestTokenData:
    def test_is_expired_true(self):
        td = TokenData(
            access_token="a", refresh_token="r", expires_at=0.0
        )
        assert td.is_expired is True

    def test_is_expired_false(self):
        td = TokenData(
            access_token="a", refresh_token="r",
            expires_at=time.time() + 3600,
        )
        assert td.is_expired is False

    def test_defaults(self):
        td = TokenData(access_token="a", refresh_token="r")
        assert td.token_type == "Bearer"
        assert td.expires_at == 0.0


class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.yoto.client_id == ""
        assert cfg.spotify.client_id == ""
        assert cfg.spotify.client_secret == ""
        assert cfg.download.format == "mp3"
        assert cfg.download.output_dir == "~/.cache/spot2yoto/downloads"
        assert cfg.sync.max_retries == 3
        assert cfg.sync.transcode_poll_interval == 2
        assert cfg.sync.transcode_poll_max_attempts == 60

    def test_from_dict(self):
        cfg = AppConfig.model_validate({
            "yoto": {"client_id": "yid"},
            "spotify": {"client_id": "sid", "client_secret": "sec"},
        })
        assert cfg.yoto.client_id == "yid"
        assert cfg.spotify.client_id == "sid"

    def test_partial_dict(self):
        cfg = AppConfig.model_validate({"yoto": {"client_id": "x"}})
        assert cfg.yoto.client_id == "x"
        assert cfg.spotify.client_id == ""  # default


class TestSpotifyModels:
    def test_track_creation(self):
        t = SpotifyTrack(
            track_id="abc",
            name="Test",
            artist="Art",
            duration_ms=200000,
            spotify_url="https://example.com",
            position=0,
        )
        assert t.album_image_url == ""

    def test_playlist_creation(self):
        p = SpotifyPlaylist(
            playlist_id="pl1",
            name="My List",
            snapshot_id="snap1",
            tracks=[],
        )
        assert p.cover_image_url == ""
        assert p.tracks == []


class TestYotoModels:
    def test_card_defaults(self):
        c = YotoCard(card_id="c1")
        assert c.title == ""
        assert c.description == ""

    def test_upload_url_none(self):
        u = YotoUploadUrl(upload_id="u1")
        assert u.upload_url is None

    def test_transcode_result(self):
        r = YotoTranscodeResult(
            upload_id="u1", transcoded_sha256="abc123"
        )
        assert r.duration == 0
        assert r.channels == "stereo"

    def test_chapter_defaults(self):
        ch = YotoChapter(title="Ch1", transcoded_sha256="sha")
        assert ch.icon_media_id == ""

    def test_content_payload(self):
        p = YotoContentPayload(
            card_id="c1", title="T", chapters=[]
        )
        assert p.cover_image_url == ""
        assert p.description == ""
