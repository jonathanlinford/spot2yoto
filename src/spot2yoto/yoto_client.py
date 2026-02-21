"""Yoto API client — upload flow, cards, content CRUD."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import httpx

from spot2yoto.exceptions import TranscodeError, UploadError, YotoAPIError
from spot2yoto.models import (
    TokenData,
    YotoCard,
    YotoChapter,
    YotoContentPayload,
    YotoTranscodeResult,
    YotoUploadUrl,
)

API_BASE = "https://api.yotoplay.com"
MAX_RETRY_AFTER = 60


class YotoClient:
    def __init__(self, tokens: TokenData, client_id: str = "", account_name: str = "default"):
        self._tokens = tokens
        self._client_id = client_id
        self._account_name = account_name
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {tokens.access_token}"},
            timeout=60.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> YotoClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _refresh_if_expired(self) -> None:
        if self._tokens.is_expired and self._client_id:
            from spot2yoto.yoto_auth import refresh_access_token, save_tokens

            self._tokens = refresh_access_token(self._client_id, self._tokens.refresh_token)
            save_tokens(self._tokens, account_name=self._account_name)
            self._client.headers["Authorization"] = f"Bearer {self._tokens.access_token}"

    def _request(self, method: str, path: str, **kwargs: object) -> dict:
        self._refresh_if_expired()
        max_retries = 3
        for attempt in range(max_retries):
            resp = self._client.request(method, path, **kwargs)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                if retry_after > MAX_RETRY_AFTER:
                    raise YotoAPIError(
                        f"Rate limited with Retry-After {retry_after}s (exceeds {MAX_RETRY_AFTER}s cap)",
                        status_code=429,
                    )
                time.sleep(retry_after)
                continue
            if resp.status_code == 401 and self._client_id and attempt < max_retries - 1:
                from spot2yoto.yoto_auth import refresh_access_token, save_tokens

                self._tokens = refresh_access_token(self._client_id, self._tokens.refresh_token)
                save_tokens(self._tokens, account_name=self._account_name)
                self._client.headers["Authorization"] = f"Bearer {self._tokens.access_token}"
                continue
            ok = {200, 201} if method == "POST" else {200}
            if resp.status_code not in ok:
                raise YotoAPIError(
                    f"{method} {path} failed ({resp.status_code}): {resp.text}",
                    status_code=resp.status_code,
                )
            return resp.json()
        raise YotoAPIError(f"{method} {path} failed after {max_retries} retries", status_code=429)

    def _get(self, path: str, **kwargs: object) -> dict:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs: object) -> dict:
        return self._request("POST", path, **kwargs)

    # --- Cards ---

    def list_cards(self) -> list[YotoCard]:
        """List all cards in the family library."""
        data = self._get("/card/family/library")
        cards = []
        for c in data.get("cards", []):
            card_data = c.get("card", {})
            cards.append(
                YotoCard(
                    card_id=c["cardId"],
                    title=card_data.get("title", ""),
                    description=card_data.get("metadata", {}).get("description", ""),
                )
            )
        return cards

    def list_myo_cards(self) -> list[YotoCard]:
        """List only user-created MYO cards."""
        data = self._get("/content/mine")
        cards = []
        for c in data.get("cards", []):
            cards.append(
                YotoCard(
                    card_id=c["cardId"],
                    title=c.get("title", ""),
                    description=c.get("metadata", {}).get("description", ""),
                )
            )
        return cards

    def get_card(self, card_id: str) -> dict:
        return self._get(f"/card/{card_id}")

    def get_content(self, card_id: str) -> dict:
        return self._get(f"/content/{card_id}")

    # --- Cover image ---

    def upload_cover_image(self, image_url: str) -> str:
        """Upload a cover image to Yoto via URL. Returns the Yoto media URL."""
        data = self._post(
            "/media/coverImage/user/me/upload",
            params={"autoconvert": "true", "coverType": "myo", "imageUrl": image_url},
        )
        return data.get("coverImage", {}).get("mediaUrl", "")

    def upload_display_icon(self, image_url: str) -> str:
        """Upload a 16x16 display icon to Yoto from a URL. Returns the media ID."""
        # Download the image first, then upload bytes
        img_resp = httpx.get(image_url, timeout=30.0)
        if img_resp.status_code != 200:
            raise UploadError(
                f"Failed to download icon image ({img_resp.status_code})",
                status_code=img_resp.status_code,
            )
        content_type = img_resp.headers.get("content-type", "image/jpeg")
        data = self._post(
            "/media/displayIcons/user/me/upload",
            params={"autoConvert": "true"},
            content=img_resp.content,
            headers={"Content-Type": content_type},
        )
        return data.get("displayIcon", {}).get("mediaId", "")

    # --- Upload flow (4 steps) ---

    def get_upload_url(self, file_path: Path) -> YotoUploadUrl:
        sha = _file_sha256(file_path)
        data = self._get(
            "/media/transcode/audio/uploadUrl",
            params={"sha256": sha, "filename": file_path.name},
        )
        upload = data.get("upload", data)
        return YotoUploadUrl(
            upload_url=upload.get("uploadUrl", ""),
            upload_id=upload["uploadId"],
        )

    def upload_file(self, upload_url: str, file_path: Path) -> None:
        with open(file_path, "rb") as f:
            content = f.read()
        resp = httpx.put(
            upload_url,
            content=content,
            headers={"Content-Type": "audio/mpeg"},
            timeout=120.0,
        )
        if resp.status_code not in (200, 201):
            raise UploadError(
                f"File upload failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )

    def poll_transcode(
        self,
        upload_id: str,
        interval: int = 2,
        max_attempts: int = 60,
    ) -> YotoTranscodeResult:
        self._refresh_if_expired()
        path = f"/media/upload/{upload_id}/transcoded"
        for attempt in range(max_attempts):
            resp = self._client.get(path, params={"loudnorm": "false"})
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2 ** min(attempt, 5)))
                if retry_after > MAX_RETRY_AFTER:
                    raise TranscodeError(
                        f"Rate limited with Retry-After {retry_after}s (exceeds {MAX_RETRY_AFTER}s cap)",
                        status_code=429,
                    )
                time.sleep(retry_after)
                continue
            if resp.status_code == 202:
                # Still transcoding
                time.sleep(interval)
                continue
            if resp.status_code != 200:
                raise TranscodeError(
                    f"Transcode check failed ({resp.status_code}): {resp.text}",
                    status_code=resp.status_code,
                )
            data = resp.json()
            transcode = data.get("transcode", data)
            sha = transcode.get("transcodedSha256")
            if sha:
                return YotoTranscodeResult(
                    upload_id=upload_id,
                    transcoded_sha256=sha,
                    duration=transcode.get("transcodedInfo", {}).get("duration", 0),
                    file_size=transcode.get("transcodedInfo", {}).get("fileSize", 0),
                    channels=transcode.get("transcodedInfo", {}).get("channels", "stereo"),
                )
            time.sleep(interval)
        raise TranscodeError(
            f"Transcode timed out for upload {upload_id}",
            status_code=None,
        )

    def upload_track(
        self,
        file_path: Path,
        poll_interval: int = 2,
        poll_max_attempts: int = 60,
    ) -> YotoTranscodeResult:
        url_info = self.get_upload_url(file_path)
        if url_info.upload_url:
            self.upload_file(url_info.upload_url, file_path)
        # If upload_url is empty, file already exists on Yoto servers
        return self.poll_transcode(
            url_info.upload_id,
            interval=poll_interval,
            max_attempts=poll_max_attempts,
        )

    # --- Content ---

    def create_card_content(self, payload: YotoContentPayload) -> dict:
        """Create a new MYO card with content."""
        body = _build_content_body(payload)
        return self._post("/content", json=body)

    def update_card_content(self, payload: YotoContentPayload) -> dict:
        """Update an existing MYO card's content (cardId in body, POST /content)."""
        body = _build_content_body(payload)
        body["cardId"] = payload.card_id
        return self._post("/content", json=body)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_content_body(payload: YotoContentPayload) -> dict:
    chapters = []
    for i, ch in enumerate(payload.chapters):
        key = str(i + 1).zfill(2)
        track = {
            "key": key,
            "title": ch.title,
            "trackUrl": f"yoto:#{ch.transcoded_sha256}",
            "duration": ch.duration,
            "fileSize": ch.file_size,
            "channels": ch.channels,
            "format": "aac",
            "type": "audio",
            "overlayLabel": key,
        }
        chapter_entry: dict = {
            "key": key,
            "title": ch.title,
            "overlayLabel": key,
            "duration": ch.duration,
            "tracks": [track],
        }
        if ch.icon_media_id:
            icon_ref = f"yoto:#{ch.icon_media_id}"
            track["display"] = {"icon16x16": icon_ref}
            chapter_entry["display"] = {"icon16x16": icon_ref}
        chapters.append(chapter_entry)
    body: dict = {
        "title": payload.title,
        "content": {"chapters": chapters},
    }
    metadata: dict = {}
    if payload.description:
        metadata["description"] = payload.description
    if payload.cover_image_url:
        metadata["cover"] = {"imageL": payload.cover_image_url}
    if metadata:
        body["metadata"] = metadata
    return body
