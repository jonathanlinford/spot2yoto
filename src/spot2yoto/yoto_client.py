"""Yoto API client — upload flow, cards, content CRUD."""

from __future__ import annotations

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


class YotoClient:
    def __init__(self, tokens: TokenData):
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

    def _get(self, path: str, **kwargs: object) -> dict:
        resp = self._client.get(path, **kwargs)
        if resp.status_code != 200:
            raise YotoAPIError(
                f"GET {path} failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    def _post(self, path: str, **kwargs: object) -> dict:
        resp = self._client.post(path, **kwargs)
        if resp.status_code not in (200, 201):
            raise YotoAPIError(
                f"POST {path} failed ({resp.status_code}): {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    # --- Cards ---

    def list_cards(self) -> list[YotoCard]:
        data = self._get("/card/family")
        cards = []
        for c in data.get("cards", []):
            cards.append(
                YotoCard(
                    card_id=c["cardId"],
                    title=c.get("card", {}).get("title", ""),
                    description=c.get("card", {}).get("description", ""),
                )
            )
        return cards

    def get_card(self, card_id: str) -> dict:
        return self._get(f"/card/{card_id}")

    # --- Upload flow (4 steps) ---

    def get_upload_url(self) -> YotoUploadUrl:
        data = self._get("/media/transcode/audio/uploadUrl")
        return YotoUploadUrl(
            upload_url=data["uploadUrl"],
            upload_id=data["uploadId"],
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
        for _ in range(max_attempts):
            data = self._get(f"/media/upload/{upload_id}/transcoded")
            sha = data.get("transcodedSha256")
            if sha:
                return YotoTranscodeResult(
                    upload_id=upload_id,
                    transcoded_sha256=sha,
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
        url_info = self.get_upload_url()
        self.upload_file(url_info.upload_url, file_path)
        return self.poll_transcode(
            url_info.upload_id,
            interval=poll_interval,
            max_attempts=poll_max_attempts,
        )

    # --- Content ---

    def update_card_content(self, payload: YotoContentPayload) -> dict:
        chapters = []
        for ch in payload.chapters:
            chapters.append(
                {
                    "title": ch.title,
                    "key": ch.key,
                    "duration": ch.duration,
                }
            )
        body = {
            "cardId": payload.card_id,
            "title": payload.title,
            "content": {
                "editVersion": 2,
                "chapters": chapters,
            },
        }
        return self._post("/card/content", json=body)
