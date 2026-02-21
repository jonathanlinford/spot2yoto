"""Pydantic data models for spot2yoto."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# --- Config models ---


class ChapterMode(str, Enum):
    ONE_PER_TRACK = "one_per_track"


class YotoConfig(BaseModel):
    client_id: str = "REDACTED_YOTO_CLIENT_ID"


class SpotifyConfig(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class DownloadConfig(BaseModel):
    format: str = "mp3"
    output_dir: str = "~/.cache/spot2yoto/downloads"


class MappingConfig(BaseModel):
    name: str
    spotify_url: str
    yoto_card_id: str = ""
    chapter_mode: ChapterMode = ChapterMode.ONE_PER_TRACK


class SyncConfig(BaseModel):
    max_retries: int = 3
    transcode_poll_interval: int = 2
    transcode_poll_max_attempts: int = 60
    parallel_uploads: int = 3
    cleanup_downloads: bool = True


class AppConfig(BaseModel):
    yoto: YotoConfig = Field(default_factory=YotoConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    mappings: list[MappingConfig] = Field(default_factory=list)
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


class SpotifyPlaylist(BaseModel):
    playlist_id: str
    name: str
    snapshot_id: str
    tracks: list[SpotifyTrack]


# --- Yoto data models ---


class YotoCard(BaseModel):
    card_id: str
    title: str = ""
    description: str = ""


class YotoUploadUrl(BaseModel):
    upload_url: str
    upload_id: str


class YotoTranscodeResult(BaseModel):
    upload_id: str
    transcoded_sha256: str


class YotoChapter(BaseModel):
    title: str
    key: str  # the transcoded file key/sha256
    duration: int = 0  # seconds


class YotoContentPayload(BaseModel):
    card_id: str
    title: str
    chapters: list[YotoChapter]
