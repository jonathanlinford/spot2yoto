"""Spotify playlist metadata (spotipy) and audio download (spotdl)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from spot2yoto.exceptions import DownloadError, SpotifyError
from spot2yoto.models import SpotifyPlaylist, SpotifyTrack


def _extract_playlist_id(url: str) -> str:
    match = re.search(r"playlist/([a-zA-Z0-9]+)", url)
    if not match:
        raise SpotifyError(f"Cannot extract playlist ID from: {url}")
    return match.group(1)


def get_spotify_client(client_id: str, client_secret: str) -> spotipy.Spotify:
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
    )


def fetch_playlist(sp: spotipy.Spotify, playlist_url: str) -> SpotifyPlaylist:
    playlist_id = _extract_playlist_id(playlist_url)
    data = sp.playlist(playlist_id)
    if not data:
        raise SpotifyError(f"Playlist not found: {playlist_id}")

    tracks: list[SpotifyTrack] = []
    results = data["tracks"]
    position = 0
    while True:
        for item in results["items"]:
            t = item.get("track")
            if not t or not t.get("id"):
                position += 1
                continue
            artists = ", ".join(a["name"] for a in t.get("artists", []))
            tracks.append(
                SpotifyTrack(
                    track_id=t["id"],
                    name=t["name"],
                    artist=artists,
                    duration_ms=t.get("duration_ms", 0),
                    spotify_url=t["external_urls"].get("spotify", ""),
                    position=position,
                )
            )
            position += 1
        if results["next"]:
            results = sp.next(results)
        else:
            break

    return SpotifyPlaylist(
        playlist_id=playlist_id,
        name=data["name"],
        snapshot_id=data["snapshot_id"],
        tracks=tracks,
    )


def download_track(
    spotify_url: str,
    output_dir: Path,
    audio_format: str = "mp3",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "spotdl",
            spotify_url,
            "--output", str(output_dir),
            "--format", audio_format,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise DownloadError(
            f"spotdl failed for {spotify_url}: {result.stderr}"
        )
    # Find the downloaded file (spotdl names it based on track metadata)
    mp3_files = sorted(output_dir.glob(f"*.{audio_format}"), key=lambda p: p.stat().st_mtime)
    if not mp3_files:
        raise DownloadError(f"No {audio_format} file found after spotdl download")
    return mp3_files[-1]
