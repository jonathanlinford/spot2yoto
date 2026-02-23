"""Tests for Yoto auth (token save/load, refresh, ensure_valid)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spot2yoto.exceptions import AuthError
from spot2yoto.models import TokenData


class TestSaveLoadTokens:
    def test_save_and_load(self, tmp_path: Path, sample_tokens: TokenData):
        import spot2yoto.yoto_auth as auth

        with patch.object(auth, "TOKENS_DIR", tmp_path):
            auth.save_tokens(sample_tokens, account_name="test")
            loaded = auth.load_tokens(account_name="test")

        assert loaded is not None
        assert loaded.access_token == sample_tokens.access_token
        assert loaded.refresh_token == sample_tokens.refresh_token

    def test_load_missing(self, tmp_path: Path):
        import spot2yoto.yoto_auth as auth

        with patch.object(auth, "TOKENS_DIR", tmp_path):
            result = auth.load_tokens(account_name="nonexistent")
        assert result is None

    def test_load_invalid_json(self, tmp_path: Path):
        import spot2yoto.yoto_auth as auth

        with patch.object(auth, "TOKENS_DIR", tmp_path):
            (tmp_path / "bad.json").write_text("not json")
            result = auth.load_tokens(account_name="bad")
        assert result is None

    def test_save_creates_dir(self, tmp_path: Path, sample_tokens: TokenData):
        import spot2yoto.yoto_auth as auth

        tokens_dir = tmp_path / "sub" / "tokens"
        with patch.object(auth, "TOKENS_DIR", tokens_dir):
            auth.save_tokens(sample_tokens, account_name="test")
        assert (tokens_dir / "test.json").exists()

    def test_save_sets_permissions(self, tmp_path: Path, sample_tokens: TokenData):
        import spot2yoto.yoto_auth as auth

        with patch.object(auth, "TOKENS_DIR", tmp_path):
            auth.save_tokens(sample_tokens, account_name="perm")
            p = tmp_path / "perm.json"
            assert p.stat().st_mode & 0o777 == 0o600


class TestRefreshAccessToken:
    def test_successful_refresh(self):
        from spot2yoto.yoto_auth import refresh_access_token

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "token_type": "Bearer",
            "expires_in": 86400,
        }

        with patch("spot2yoto.yoto_auth.httpx.post", return_value=mock_resp):
            result = refresh_access_token("client-id", "old-refresh")

        assert result.access_token == "new-access"
        assert result.refresh_token == "new-refresh"

    def test_refresh_failure(self):
        from spot2yoto.yoto_auth import refresh_access_token

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        with patch("spot2yoto.yoto_auth.httpx.post", return_value=mock_resp):
            with pytest.raises(AuthError, match="Token refresh failed"):
                refresh_access_token("client-id", "bad-refresh")

    def test_refresh_preserves_refresh_token(self):
        """If server doesn't return new refresh_token, keep old one."""
        from spot2yoto.yoto_auth import refresh_access_token

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new-access",
            "token_type": "Bearer",
            "expires_in": 86400,
        }

        with patch("spot2yoto.yoto_auth.httpx.post", return_value=mock_resp):
            result = refresh_access_token("client-id", "keep-this")

        assert result.refresh_token == "keep-this"


class TestEnsureValidToken:
    def test_valid_token(self, tmp_path: Path, sample_tokens: TokenData):
        import spot2yoto.yoto_auth as auth

        with patch.object(auth, "TOKENS_DIR", tmp_path):
            auth.save_tokens(sample_tokens, account_name="test")
            result = auth.ensure_valid_token("client-id", account_name="test")

        assert result.access_token == sample_tokens.access_token

    def test_no_token_raises(self, tmp_path: Path):
        import spot2yoto.yoto_auth as auth

        with patch.object(auth, "TOKENS_DIR", tmp_path):
            with pytest.raises(AuthError, match="No Yoto tokens found"):
                auth.ensure_valid_token("client-id", account_name="missing")

    def test_expired_token_refreshes(self, tmp_path: Path, expired_tokens: TokenData):
        import spot2yoto.yoto_auth as auth

        new_tokens = TokenData(
            access_token="refreshed",
            refresh_token="new-refresh",
            expires_at=time.time() + 3600,
        )

        with patch.object(auth, "TOKENS_DIR", tmp_path):
            auth.save_tokens(expired_tokens, account_name="test")
            with patch.object(auth, "refresh_access_token", return_value=new_tokens):
                result = auth.ensure_valid_token("client-id", account_name="test")

        assert result.access_token == "refreshed"


class TestListAccounts:
    def test_empty(self, tmp_path: Path):
        import spot2yoto.yoto_auth as auth

        with patch.object(auth, "TOKENS_DIR", tmp_path / "nonexistent"):
            result = auth.list_accounts()
        assert result == []

    def test_with_accounts(self, tmp_path: Path, sample_tokens: TokenData):
        import spot2yoto.yoto_auth as auth

        with patch.object(auth, "TOKENS_DIR", tmp_path):
            auth.save_tokens(sample_tokens, account_name="alice")
            auth.save_tokens(sample_tokens, account_name="bob")
            result = auth.list_accounts()

        assert result == ["alice", "bob"]
