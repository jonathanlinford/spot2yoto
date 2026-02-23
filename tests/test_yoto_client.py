"""Tests for Yoto API client."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from spot2yoto.exceptions import YotoAPIError
from spot2yoto.models import (
    TokenData,
    YotoChapter,
    YotoContentPayload,
)
from spot2yoto.yoto_client import YotoClient, _build_content_body, file_sha256


class TestFileSha256:
    def test_correct_hash(self, mp3_file: Path):
        expected = hashlib.sha256(mp3_file.read_bytes()).hexdigest()
        assert file_sha256(mp3_file) == expected

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert file_sha256(f) == expected


class TestBuildContentBody:
    def test_basic(self):
        payload = YotoContentPayload(
            card_id="c1",
            title="My Card",
            chapters=[
                YotoChapter(title="Ch1", transcoded_sha256="sha1", duration=60),
            ],
        )
        body = _build_content_body(payload)
        assert body["title"] == "My Card"
        assert len(body["content"]["chapters"]) == 1
        ch = body["content"]["chapters"][0]
        assert ch["key"] == "01"
        assert ch["title"] == "Ch1"
        assert ch["tracks"][0]["trackUrl"] == "yoto:#sha1"

    def test_multiple_chapters(self):
        chapters = [
            YotoChapter(title=f"Ch{i}", transcoded_sha256=f"sha{i}")
            for i in range(3)
        ]
        payload = YotoContentPayload(
            card_id="c1", title="T", chapters=chapters
        )
        body = _build_content_body(payload)
        keys = [ch["key"] for ch in body["content"]["chapters"]]
        assert keys == ["01", "02", "03"]

    def test_with_cover_and_description(self):
        payload = YotoContentPayload(
            card_id="c1",
            title="T",
            chapters=[YotoChapter(title="Ch", transcoded_sha256="s")],
            cover_image_url="https://img.com/cover.jpg",
            description="My playlist desc",
        )
        body = _build_content_body(payload)
        assert body["metadata"]["cover"]["imageL"] == "https://img.com/cover.jpg"
        assert body["metadata"]["description"] == "My playlist desc"

    def test_no_metadata_when_empty(self):
        payload = YotoContentPayload(
            card_id="c1",
            title="T",
            chapters=[YotoChapter(title="Ch", transcoded_sha256="s")],
        )
        body = _build_content_body(payload)
        assert "metadata" not in body

    def test_icon_media_id(self):
        payload = YotoContentPayload(
            card_id="c1",
            title="T",
            chapters=[
                YotoChapter(title="Ch", transcoded_sha256="s", icon_media_id="icon-123"),
            ],
        )
        body = _build_content_body(payload)
        ch = body["content"]["chapters"][0]
        assert ch["display"]["icon16x16"] == "yoto:#icon-123"
        assert ch["tracks"][0]["display"]["icon16x16"] == "yoto:#icon-123"


class TestYotoClientRequest:
    def _make_client(self, tokens: TokenData | None = None) -> YotoClient:
        t = tokens or TokenData(
            access_token="test",
            refresh_token="refresh",
            expires_at=time.time() + 3600,
        )
        return YotoClient(t, client_id="test-client")

    def test_successful_get(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"cards": []}
        with patch.object(client._client, "request", return_value=mock_resp):
            result = client._get("/test")
        assert result == {"cards": []}

    def test_successful_post(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"ok": True}
        with patch.object(client._client, "request", return_value=mock_resp):
            result = client._post("/test", json={"data": 1})
        assert result == {"ok": True}

    def test_error_raises(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        with patch.object(client._client, "request", return_value=mock_resp):
            with pytest.raises(YotoAPIError, match="500"):
                client._get("/test")

    def test_429_retries(self):
        client = self._make_client()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "1"}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"ok": True}

        with patch.object(client._client, "request", side_effect=[resp_429, resp_200]):
            with patch("spot2yoto.yoto_client.time.sleep"):
                result = client._get("/test")
        assert result == {"ok": True}

    def test_429_cap_exceeded(self):
        client = self._make_client()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "999"}

        with patch.object(client._client, "request", return_value=resp_429):
            with pytest.raises(YotoAPIError, match="rate limit exceeded"):
                client._get("/test")

    def test_401_refreshes_token(self):
        client = self._make_client()
        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"ok": True}

        new_tokens = TokenData(
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at=time.time() + 3600,
        )

        with patch.object(client._client, "request", side_effect=[resp_401, resp_200]):
            with patch("spot2yoto.yoto_auth.refresh_access_token", return_value=new_tokens) as mock_refresh:
                with patch("spot2yoto.yoto_auth.save_tokens"):
                    result = client._get("/test")
        assert result == {"ok": True}
        mock_refresh.assert_called_once()

    def test_exhausted_retries(self):
        client = self._make_client()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "1"}

        with patch.object(client._client, "request", return_value=resp_429):
            with patch("spot2yoto.yoto_client.time.sleep"):
                with pytest.raises(YotoAPIError, match="retries"):
                    client._get("/test")

    def test_context_manager(self, sample_tokens: TokenData):
        with YotoClient(sample_tokens) as client:
            assert client._tokens == sample_tokens
