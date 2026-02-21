"""Spotify playlist metadata (spotipy) and audio download (spotdl)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from spot2yoto.exceptions import DownloadError, SpotifyError
from spot2yoto.models import SpotifyPlaylist, SpotifyTrack

CACHE_PATH = Path("~/.config/spot2yoto/.spotify_cache").expanduser()


def _extract_playlist_id(url: str) -> str:
    match = re.search(r"playlist/([a-zA-Z0-9]+)", url)
    if not match:
        raise SpotifyError(f"Cannot extract playlist ID from: {url}")
    return match.group(1)


def get_spotify_client(client_id: str, client_secret: str) -> spotipy.Spotify:
    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://127.0.0.1:8888/callback",
            scope="playlist-read-private playlist-read-collaborative",
            cache_path=str(CACHE_PATH),
            open_browser=True,
        )
    )


def _extract_track(entry: dict) -> dict | None:
    """Extract track data from a playlist item, handling both API formats."""
    # New format: track data under "item" key
    t = entry.get("item")
    if t and t.get("id"):
        return t
    # Old format: track data under "track" key
    t = entry.get("track")
    if t and t.get("id"):
        return t
    return None


def fetch_playlist(sp: spotipy.Spotify, playlist_url: str) -> SpotifyPlaylist:
    playlist_id = _extract_playlist_id(playlist_url)
    data = sp.playlist(playlist_id)
    if not data:
        raise SpotifyError(f"Playlist not found: {playlist_id}")

    tracks: list[SpotifyTrack] = []
    # API may return tracks under "tracks" or "items" key
    results = data.get("tracks") or data.get("items")
    if not results:
        raise SpotifyError(f"No track data in playlist response for {playlist_id}")
    position = 0
    while True:
        for entry in results["items"]:
            t = _extract_track(entry)
            if not t:
                position += 1
                continue
            artists = ", ".join(a["name"] for a in t.get("artists", []))
            album_images = t.get("album", {}).get("images", [])
            album_image_url = album_images[0]["url"] if album_images else ""
            tracks.append(
                SpotifyTrack(
                    track_id=t["id"],
                    name=t["name"],
                    artist=artists,
                    duration_ms=t.get("duration_ms", 0),
                    spotify_url=t["external_urls"].get("spotify", ""),
                    position=position,
                    album_image_url=album_image_url,
                )
            )
            position += 1
        if results.get("next"):
            results = sp.next(results)
        else:
            break

    # Get the largest cover image URL
    images = data.get("images", [])
    cover_url = images[0]["url"] if images else ""

    return SpotifyPlaylist(
        playlist_id=playlist_id,
        name=data["name"],
        snapshot_id=data["snapshot_id"],
        tracks=tracks,
        cover_image_url=cover_url,
    )


def download_track(
    track_name: str,
    artist: str,
    output_dir: Path,
    audio_format: str = "mp3",
    track_id: str | None = None,
) -> Path:
    """Download a track via yt-dlp by searching YouTube Music.

    When *track_id* is provided the file is saved as ``{track_id}.{format}``
    and a cache check is performed first — if the file already exists the
    download is skipped entirely.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Cache hit — file already downloaded in a previous run
    if track_id:
        cached = output_dir / f"{track_id}.{audio_format}"
        if cached.exists():
            return cached

    search_query = f"ytsearch1:{artist} - {track_name}"
    if track_id:
        output_template = str(output_dir / f"{track_id}.%(ext)s")
    else:
        output_template = str(output_dir / "%(title)s.%(ext)s")

    result = subprocess.run(
        [
            "yt-dlp",
            search_query,
            "-x",
            "--audio-format", audio_format,
            "-o", output_template,
            "--no-playlist",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise DownloadError(
            f"yt-dlp failed for '{artist} - {track_name}': {result.stderr or result.stdout}"
        )

    if track_id:
        expected = output_dir / f"{track_id}.{audio_format}"
        if expected.exists():
            return expected

    files = sorted(output_dir.glob(f"*.{audio_format}"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise DownloadError(f"No {audio_format} file found after yt-dlp download")
    return files[-1]
