"""Pydantic data models for spot2yoto."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


# --- Config models ---


class YotoConfig(BaseModel):
    client_id: str = ""


class SpotifyConfig(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class DownloadConfig(BaseModel):
    format: str = "mp3"
    output_dir: str = "~/.cache/spot2yoto/downloads"


class SyncConfig(BaseModel):
    max_retries: int = 3
    transcode_poll_interval: int = 2
    transcode_poll_max_attempts: int = 60


class AppConfig(BaseModel):
    yoto: YotoConfig = Field(default_factory=YotoConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)


# --- Token models ---


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        return datetime.now().timestamp() >= self.expires_at


# --- Spotify data models ---


class SpotifyTrack(BaseModel):
    track_id: str
    name: str
    artist: str
    duration_ms: int
    spotify_url: str
    position: int
    album_image_url: str = ""


class SpotifyPlaylist(BaseModel):
    playlist_id: str
    name: str
    snapshot_id: str
    tracks: list[SpotifyTrack]
    cover_image_url: str = ""


# --- Yoto data models ---


class YotoCard(BaseModel):
    card_id: str
    title: str = ""
    description: str = ""


class YotoUploadUrl(BaseModel):
    upload_url: str | None = None  # None if file already exists on Yoto
    upload_id: str


class YotoTranscodeResult(BaseModel):
    upload_id: str
    transcoded_sha256: str
    duration: int = 0  # seconds
    file_size: int = 0
    channels: str = "stereo"


class YotoChapter(BaseModel):
    title: str
    transcoded_sha256: str  # used as yoto:#sha in trackUrl
    duration: int = 0  # seconds
    file_size: int = 0
    channels: str = "stereo"
    icon_media_id: str = ""  # 16x16 display icon for Yoto player


class YotoContentPayload(BaseModel):
    card_id: str
    title: str
    chapters: list[YotoChapter]
    cover_image_url: str = ""  # Yoto media URL for cover art
    description: str = ""  # Preserve card description (contains Spotify link)
