"""Sync orchestrator — discover mappings from card descriptions, diff, download, upload."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

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
from spot2yoto import ui
from spot2yoto.ui import SyncStats
from spot2yoto.yoto_client import YotoClient, file_sha256

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
                    ui.dim(f"  Validated: {card.title} -> {data['name']}")
                valid_urls.append(url)
            except Exception as e:
                ui.warning(f"  Skipping playlist on '{card.title}': unreachable ({e})")
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


def _fetch_and_merge_playlists(
    sp: "spotipy.Spotify",
    urls: list[str],
    verbose: bool = False,
) -> tuple[list[SpotifyTrack], str, str, str]:
    """Fetch all playlists, merge tracks, dedup by track_id.

    Returns (all_tracks, composite_snapshot, card_title, cover_url_source).
    """
    all_tracks: list[SpotifyTrack] = []
    seen_ids: set[str] = set()
    snapshot_parts: list[str] = []
    cover_url_source = ""
    card_title = ""

    for url in urls:
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

    composite_snapshot = "|".join(sorted(snapshot_parts))

    if verbose:
        ui.dim(f"  Playlists: {len(urls)}, Tracks: {len(all_tracks)} (deduped)")
        ui.dim(f"  Composite snapshot: {composite_snapshot}")

    return all_tracks, composite_snapshot, card_title, cover_url_source


def _download_and_upload_new_tracks(
    diff: TrackDiff,
    config: AppConfig,
    yoto: YotoClient,
    db: StateDB,
    card_id: str,
    verbose: bool = False,
    stats: SyncStats | None = None,
) -> None:
    """Download new tracks via yt-dlp and upload to Yoto."""
    output_dir = Path(config.download.output_dir).expanduser()

    for track in diff.new_tracks:
        # Cross-card dedup: reuse transcoded_sha256 if track was already uploaded for another card
        existing_sha = db.get_track_sha_any(track.track_id)
        if existing_sha:
            if verbose:
                ui.status(f"  Reusing upload for: {track.artist} - {track.name}", "reuse")
            db.upsert_track(
                track_id=track.track_id,
                mapping_name=card_id,
                position=track.position,
                transcoded_sha256=existing_sha,
            )
            if stats:
                stats.reused += 1
            continue

        ui.status(f"  Downloading: {track.artist} - {track.name}", "download")
        try:
            file_path = download_track(
                track.name,
                track.artist,
                output_dir,
                config.download.format,
                track_id=track.track_id,
            )
        except Exception as e:
            ui.error(f"  ERROR downloading {track.name}: {e}")
            continue

        if stats:
            stats.downloaded += 1

        sha = file_sha256(file_path)
        ui.status(f"  Uploading: {track.name}", "upload")
        try:
            result = yoto.upload_track(
                file_path,
                poll_interval=config.sync.transcode_poll_interval,
                poll_max_attempts=config.sync.transcode_poll_max_attempts,
            )
        except Exception as e:
            ui.error(f"  ERROR uploading {track.name}: {e}")
            continue

        if stats:
            stats.uploaded += 1

        db.upsert_track(
            track_id=track.track_id,
            mapping_name=card_id,
            position=track.position,
            transcoded_sha256=result.transcoded_sha256,
            file_sha256=sha,
        )


def _upload_artwork(
    diff: TrackDiff,
    yoto: YotoClient,
    db: StateDB,
    cover_url_source: str,
    verbose: bool = False,
) -> tuple[str, dict[str, str]]:
    """Upload cover art and per-track icons. Returns (cover_url, track_icons)."""
    cover_url = ""
    if cover_url_source:
        cached = db.get_cached_media(cover_url_source)
        if cached:
            cover_url = cached
            if verbose:
                ui.dim("  Cover art cached, skipping upload")
        else:
            try:
                ui.status("  Uploading cover art...", "art")
                cover_url = yoto.upload_cover_image(cover_url_source)
                if cover_url:
                    db.cache_media(cover_url_source, cover_url, "cover")
                if verbose:
                    ui.dim(f"  Cover art uploaded: {cover_url}")
            except Exception as e:
                ui.warning(f"  Warning: cover art upload failed ({e}), continuing without it")

    track_icons: dict[str, str] = {}
    icon_cache: dict[str, str] = {}
    for track in diff.all_tracks:
        if not track.album_image_url:
            continue
        url = track.album_image_url
        if url in icon_cache:
            track_icons[track.track_id] = icon_cache[url]
            continue
        cached = db.get_cached_media(url)
        if cached:
            icon_cache[url] = cached
            track_icons[track.track_id] = cached
            continue
        try:
            if verbose:
                ui.dim(f"  Uploading icon: {track.name}")
            media_id = yoto.upload_display_icon(url)
            icon_cache[url] = media_id
            track_icons[track.track_id] = media_id
            if media_id:
                db.cache_media(url, media_id, "icon")
        except Exception as e:
            ui.warning(f"  Warning: icon upload failed for {track.name} ({e})")

    return cover_url, track_icons


def _build_and_update_card(
    diff: TrackDiff,
    yoto: YotoClient,
    db: StateDB,
    card: YotoCard,
    card_title: str,
    cover_url: str,
    track_icons: dict[str, str],
    verbose: bool = False,
) -> bool:
    """Build chapters and update card content. Returns True on success."""
    chapters: list[YotoChapter] = []
    for track in diff.all_tracks:
        sha = db.get_track_sha(track.track_id, card.card_id)
        if not sha:
            if verbose:
                ui.warning(f"  Warning: no SHA for {track.name}, skipping from card")
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
        ui.warning(f"  No chapters to write for '{card.title}'")
        return False

    ui.status(f"  Updating card with {len(chapters)} chapters", "card")
    payload = YotoContentPayload(
        card_id=card.card_id,
        title=card_title,
        chapters=chapters,
        cover_image_url=cover_url,
        description=card.description,
    )
    yoto.update_card_content(payload)
    return True


def sync_mapping(
    mapping: Mapping,
    config: AppConfig,
    yoto: YotoClient,
    db: StateDB,
    dry_run: bool = False,
    verbose: bool = False,
    force: bool = False,
    stats: SyncStats | None = None,
) -> bool:
    card = mapping.card
    sp = get_spotify_client(config.spotify.client_id, config.spotify.client_secret)

    all_tracks, composite_snapshot, card_title, cover_url_source = (
        _fetch_and_merge_playlists(sp, mapping.spotify_urls, verbose)
    )

    # Check snapshot — skip if unchanged
    last_snapshot = db.get_snapshot_id(card.card_id)
    if last_snapshot == composite_snapshot and not force:
        ui.status("  Up to date (snapshot unchanged)", "skip")
        if stats:
            stats.skipped += 1
        return True

    diff = compute_diff(all_tracks, db, card.card_id)

    if dry_run:
        ui.status(f"  [DRY RUN] {len(diff.new_tracks)} new, {len(diff.removed_track_ids)} removed", "dry")
        for t in diff.new_tracks:
            ui.status(f"    + {t.artist} - {t.name}", "music")
        for tid in diff.removed_track_ids:
            ui.status(f"    - track {tid}", "trash")
        return True

    # Remove deleted tracks from state
    if diff.removed_track_ids:
        db.remove_tracks(card.card_id, diff.removed_track_ids)
        if stats:
            stats.removed += len(diff.removed_track_ids)
        if verbose:
            ui.dim(f"  Removed {len(diff.removed_track_ids)} tracks from state")

    _download_and_upload_new_tracks(diff, config, yoto, db, card.card_id, verbose, stats=stats)

    # If no tracks changed, card content is identical — just update snapshot
    content_changed = bool(diff.new_tracks or diff.removed_track_ids)
    if not content_changed and not force:
        db.update_card_state(card.card_id, composite_snapshot)
        ui.status("  No track changes, skipping card update", "skip")
        return True

    cover_url, track_icons = _upload_artwork(diff, yoto, db, cover_url_source, verbose)

    ok = _build_and_update_card(diff, yoto, db, card, card_title, cover_url, track_icons, verbose)
    if not ok:
        return False

    db.update_card_state(card.card_id, composite_snapshot)
    ui.success("  Synced successfully")
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
    ui.status("Scanning MYO cards for Spotify playlist links...", "scan")
    mappings = discover_mappings(yoto, sp, verbose=verbose)
    if not mappings:
        ui.info("No MYO cards found with Spotify playlist URLs in their description.")
        return 0, 0

    stats = SyncStats(total_mappings=len(mappings))
    ui.status(f"Found {len(mappings)} card(s) with Spotify links:\n", "found")
    failures = 0
    for m in mappings:
        n = len(m.spotify_urls)
        ui.status(f"Syncing: {m.card.title} ({m.card.card_id}) -> {n} playlist(s)", "sync")
        try:
            ok = sync_mapping(m, config, yoto, db, dry_run=dry_run, verbose=verbose, force=force, stats=stats)
            if not ok:
                failures += 1
                stats.failed += 1
            else:
                stats.synced += 1
        except Exception as e:
            ui.error(f"  ERROR: {e}")
            failures += 1
            stats.failed += 1

    ui.sync_summary(stats)
    return len(mappings), failures
