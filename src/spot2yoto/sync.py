"""Sync orchestrator — discover mappings from card descriptions, diff, download, upload."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    import spotipy

from spot2yoto.models import (
    AppConfig,
    SpotifyTrack,
    YotoCard,
    YotoChapter,
    YotoContentPayload,
)
from spot2yoto.spotify import download_track, fetch_playlist, get_spotify_client
from spot2yoto.state import StateDB
from spot2yoto.yoto_client import YotoClient

SPOTIFY_URL_RE = re.compile(r"https://open\.spotify\.com/playlist/[a-zA-Z0-9]+[^\s]*")


@dataclass
class Mapping:
    """A discovered mapping: MYO card with Spotify playlist URL(s) in its description."""
    card: YotoCard
    spotify_urls: list[str]


@dataclass
class TrackDiff:
    new_tracks: list[SpotifyTrack] = field(default_factory=list)
    removed_track_ids: list[str] = field(default_factory=list)
    all_tracks: list[SpotifyTrack] = field(default_factory=list)


def discover_mappings(
    yoto: YotoClient,
    sp: "spotipy.Spotify",
    verbose: bool = False,
) -> list[Mapping]:
    """Scan MYO card descriptions for Spotify playlist URLs, validate each."""
    cards = yoto.list_myo_cards()
    mappings = []
    for card in cards:
        matches = SPOTIFY_URL_RE.findall(card.description)
        if not matches:
            continue
        urls = [m.split("?")[0] for m in matches]  # strip query params
        # Validate each URL, keep only reachable ones
        valid_urls: list[str] = []
        for url in urls:
            try:
                playlist_id = re.search(r"playlist/([a-zA-Z0-9]+)", url).group(1)
                data = sp.playlist(playlist_id, fields="id,name")
                if not data:
                    raise Exception("empty response")
                if verbose:
                    click.echo(f"  Validated: {card.title} -> {data['name']}")
                valid_urls.append(url)
            except Exception as e:
                click.echo(f"  Skipping playlist on '{card.title}': unreachable ({e})")
                continue
        if valid_urls:
            mappings.append(Mapping(card=card, spotify_urls=valid_urls))
    return mappings


def compute_diff(
    all_tracks: list[SpotifyTrack],
    db: StateDB,
    mapping_name: str,
) -> TrackDiff:
    existing = {r["spotify_track_id"] for r in db.get_all_tracks(mapping_name)}
    current_ids = {t.track_id for t in all_tracks}

    new_tracks = [t for t in all_tracks if t.track_id not in existing]
    removed = [tid for tid in existing if tid not in current_ids]

    return TrackDiff(
        new_tracks=new_tracks,
        removed_track_ids=removed,
        all_tracks=all_tracks,
    )


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sync_mapping(
    mapping: Mapping,
    config: AppConfig,
    yoto: YotoClient,
    db: StateDB,
    dry_run: bool = False,
    verbose: bool = False,
    force: bool = False,
) -> bool:
    card = mapping.card
    sp = get_spotify_client(config.spotify.client_id, config.spotify.client_secret)

    # Fetch all playlists, merge tracks, dedup by track_id
    all_tracks: list[SpotifyTrack] = []
    seen_ids: set[str] = set()
    snapshot_parts: list[str] = []
    cover_url_source = ""
    card_title = ""

    for url in mapping.spotify_urls:
        playlist = fetch_playlist(sp, url)
        snapshot_parts.append(playlist.snapshot_id)
        if not card_title:
            card_title = playlist.name
        if not cover_url_source and playlist.cover_image_url:
            cover_url_source = playlist.cover_image_url
        for track in playlist.tracks:
            if track.track_id not in seen_ids:
                seen_ids.add(track.track_id)
                all_tracks.append(track)

    # Re-number positions sequentially after merge
    for i, track in enumerate(all_tracks):
        track.position = i

    # Composite snapshot for change detection
    composite_snapshot = "|".join(sorted(snapshot_parts))

    if verbose:
        click.echo(f"  Playlists: {len(mapping.spotify_urls)}, Tracks: {len(all_tracks)} (deduped)")
        click.echo(f"  Composite snapshot: {composite_snapshot}")

    # Check snapshot — skip if unchanged
    last_snapshot = db.get_snapshot_id(card.card_id)
    if last_snapshot == composite_snapshot and not force:
        click.echo(f"  Up to date (snapshot unchanged)")
        return True

    diff = compute_diff(all_tracks, db, card.card_id)

    if dry_run:
        click.echo(f"  [DRY RUN] {len(diff.new_tracks)} new, {len(diff.removed_track_ids)} removed")
        for t in diff.new_tracks:
            click.echo(f"    + {t.artist} - {t.name}")
        for tid in diff.removed_track_ids:
            click.echo(f"    - track {tid}")
        return True

    output_dir = Path(config.download.output_dir).expanduser()

    # Remove deleted tracks from state
    if diff.removed_track_ids:
        db.remove_tracks(card.card_id, diff.removed_track_ids)
        if verbose:
            click.echo(f"  Removed {len(diff.removed_track_ids)} tracks from state")

    # Download and upload new tracks
    for track in diff.new_tracks:
        # Cross-card dedup: reuse transcoded_sha256 if track was already uploaded for another card
        existing_sha = db.get_track_sha_any(track.track_id)
        if existing_sha:
            if verbose:
                click.echo(f"  Reusing upload for: {track.artist} - {track.name}")
            db.upsert_track(
                track_id=track.track_id,
                mapping_name=card.card_id,
                position=track.position,
                transcoded_sha256=existing_sha,
            )
            continue

        click.echo(f"  Downloading: {track.artist} - {track.name}")
        try:
            file_path = download_track(
                track.name,
                track.artist,
                output_dir,
                config.download.format,
                track_id=track.track_id,
            )
        except Exception as e:
            click.echo(f"  ERROR downloading {track.name}: {e}", err=True)
            continue

        sha = file_sha256(file_path)
        click.echo(f"  Uploading: {track.name}")
        try:
            result = yoto.upload_track(
                file_path,
                poll_interval=config.sync.transcode_poll_interval,
                poll_max_attempts=config.sync.transcode_poll_max_attempts,
            )
        except Exception as e:
            click.echo(f"  ERROR uploading {track.name}: {e}", err=True)
            continue

        db.upsert_track(
            track_id=track.track_id,
            mapping_name=card.card_id,
            position=track.position,
            transcoded_sha256=result.transcoded_sha256,
            file_sha256=sha,
        )

    # Upload cover art from first playlist that has one
    cover_url = ""
    if cover_url_source:
        try:
            click.echo(f"  Uploading cover art...")
            cover_url = yoto.upload_cover_image(cover_url_source)
            if verbose:
                click.echo(f"  Cover art uploaded: {cover_url}")
        except Exception as e:
            click.echo(f"  Warning: cover art upload failed ({e}), continuing without it")

    # Upload display icons (per-track album art)
    icon_cache: dict[str, str] = {}  # image_url -> media_id
    track_icons: dict[str, str] = {}  # track_id -> media_id
    for track in diff.all_tracks:
        if not track.album_image_url:
            continue
        url = track.album_image_url
        if url in icon_cache:
            track_icons[track.track_id] = icon_cache[url]
            continue
        try:
            if verbose:
                click.echo(f"  Uploading icon: {track.name}")
            media_id = yoto.upload_display_icon(url)
            icon_cache[url] = media_id
            track_icons[track.track_id] = media_id
        except Exception as e:
            click.echo(f"  Warning: icon upload failed for {track.name} ({e})")

    # Build card content from all tracks in merged order
    chapters: list[YotoChapter] = []
    for track in diff.all_tracks:
        sha = db.get_track_sha(track.track_id, card.card_id)
        if not sha:
            if verbose:
                click.echo(f"  Warning: no SHA for {track.name}, skipping from card")
            continue
        primary_artist = track.artist.split(",")[0].strip()
        chapters.append(
            YotoChapter(
                title=f"{track.name} - {primary_artist}",
                transcoded_sha256=sha,
                duration=track.duration_ms // 1000,
                icon_media_id=track_icons.get(track.track_id, ""),
            )
        )

    if not chapters:
        click.echo(f"  No chapters to write for '{card.title}'")
        return False

    click.echo(f"  Updating card with {len(chapters)} chapters")
    payload = YotoContentPayload(
        card_id=card.card_id,
        title=card_title,
        chapters=chapters,
        cover_image_url=cover_url,
        description=card.description,
    )
    yoto.update_card_content(payload)

    db.update_card_state(card.card_id, composite_snapshot)
    click.echo(f"  Synced successfully")
    return True


def sync_all(
    config: AppConfig,
    yoto: YotoClient,
    db: StateDB,
    dry_run: bool = False,
    verbose: bool = False,
    force: bool = False,
) -> tuple[int, int]:
    """Discover and sync all mappings. Returns (total, failures)."""
    sp = get_spotify_client(config.spotify.client_id, config.spotify.client_secret)
    click.echo("Scanning MYO cards for Spotify playlist links...")
    mappings = discover_mappings(yoto, sp, verbose=verbose)
    if not mappings:
        click.echo("No MYO cards found with Spotify playlist URLs in their description.")
        return 0, 0

    click.echo(f"Found {len(mappings)} card(s) with Spotify links:\n")
    failures = 0
    for m in mappings:
        n = len(m.spotify_urls)
        click.echo(f"Syncing: {m.card.title} ({m.card.card_id}) -> {n} playlist(s)")
        try:
            ok = sync_mapping(m, config, yoto, db, dry_run=dry_run, verbose=verbose, force=force)
            if not ok:
                failures += 1
        except Exception as e:
            click.echo(f"  ERROR: {e}", err=True)
            failures += 1
    return len(mappings), failures
