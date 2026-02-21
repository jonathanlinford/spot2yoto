"""OAuth device flow and token management for Yoto API."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from spot2yoto.exceptions import AuthError
from spot2yoto.models import TokenData

AUTH_BASE = "https://login.yotoplay.com"
DEFAULT_TOKEN_PATH = Path("~/.config/spot2yoto/tokens.json").expanduser()


def request_device_code(client_id: str) -> dict:
    resp = httpx.post(
        f"{AUTH_BASE}/oauth/device/code",
        data={
            "client_id": client_id,
            "scope": "offline_access",
            "audience": "https://api.yotoplay.com",
        },
    )
    if resp.status_code != 200:
        raise AuthError(f"Device code request failed ({resp.status_code}): {resp.text}")
    return resp.json()


def poll_for_token(
    client_id: str,
    device_code: str,
    interval: int = 5,
    timeout: int = 300,
) -> TokenData:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = httpx.post(
            f"{AUTH_BASE}/oauth/token",
            data={
                "client_id": client_id,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
            },
        )
        data = resp.json()
        if resp.status_code == 200:
            return TokenData(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                token_type=data.get("token_type", "Bearer"),
                expires_at=time.time() + data.get("expires_in", 86400),
            )
        error = data.get("error", "")
        if error == "authorization_pending":
            time.sleep(interval)
            continue
        if error == "slow_down":
            interval += 5
            time.sleep(interval)
            continue
        raise AuthError(f"Token polling failed: {data.get('error_description', error)}")
    raise AuthError("Device authorization timed out")


def refresh_access_token(client_id: str, refresh_token: str) -> TokenData:
    resp = httpx.post(
        f"{AUTH_BASE}/oauth/token",
        data={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    if resp.status_code != 200:
        raise AuthError(f"Token refresh failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    return TokenData(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", refresh_token),
        token_type=data.get("token_type", "Bearer"),
        expires_at=time.time() + data.get("expires_in", 86400),
    )


def save_tokens(tokens: TokenData, path: Path | None = None) -> None:
    token_path = path or DEFAULT_TOKEN_PATH
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(tokens.model_dump(), indent=2))
    token_path.chmod(0o600)


def load_tokens(path: Path | None = None) -> TokenData | None:
    token_path = path or DEFAULT_TOKEN_PATH
    if not token_path.exists():
        return None
    try:
        data = json.loads(token_path.read_text())
        return TokenData.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return None


def ensure_valid_token(client_id: str, token_path: Path | None = None) -> TokenData:
    tokens = load_tokens(token_path)
    if tokens is None:
        raise AuthError(
            "No Yoto tokens found. Run 'spot2yoto auth yoto' first."
        )
    if tokens.is_expired:
        tokens = refresh_access_token(client_id, tokens.refresh_token)
        save_tokens(tokens, token_path)
    return tokens
