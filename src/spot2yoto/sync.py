"""Sync orchestrator — diff computation, download, upload, card update."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import click

from spot2yoto.models import (
    AppConfig,
    MappingConfig,
    SpotifyPlaylist,
    SpotifyTrack,
    YotoChapter,
    YotoContentPayload,
)
from spot2yoto.spotify import download_track, fetch_playlist, get_spotify_client
from spot2yoto.state import StateDB
from spot2yoto.yoto_client import YotoClient


@dataclass
class TrackDiff:
    new_tracks: list[SpotifyTrack] = field(default_factory=list)
    removed_track_ids: list[str] = field(default_factory=list)
    all_tracks: list[SpotifyTrack] = field(default_factory=list)


def compute_diff(
    playlist: SpotifyPlaylist,
    db: StateDB,
    mapping_name: str,
) -> TrackDiff:
    existing = {r["spotify_track_id"] for r in db.get_all_tracks(mapping_name)}
    current_ids = {t.track_id for t in playlist.tracks}

    new_tracks = [t for t in playlist.tracks if t.track_id not in existing]
    removed = [tid for tid in existing if tid not in current_ids]

    return TrackDiff(
        new_tracks=new_tracks,
        removed_track_ids=removed,
        all_tracks=playlist.tracks,
    )


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sync_mapping(
    mapping: MappingConfig,
    config: AppConfig,
    yoto: YotoClient,
    db: StateDB,
    dry_run: bool = False,
    verbose: bool = False,
) -> bool:
    if not mapping.yoto_card_id:
        click.echo(f"  Skipping '{mapping.name}': no yoto_card_id configured")
        return False

    sp = get_spotify_client(config.spotify.client_id, config.spotify.client_secret)
    playlist = fetch_playlist(sp, mapping.spotify_url)

    if verbose:
        click.echo(f"  Playlist: {playlist.name} ({len(playlist.tracks)} tracks)")
        click.echo(f"  Snapshot: {playlist.snapshot_id}")

    # Check snapshot_id — skip if unchanged
    last_snapshot = db.get_snapshot_id(mapping.name)
    if last_snapshot == playlist.snapshot_id:
        click.echo(f"  '{mapping.name}' is up to date (snapshot unchanged)")
        return True

    diff = compute_diff(playlist, db, mapping.name)

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
        db.remove_tracks(mapping.name, diff.removed_track_ids)
        if verbose:
            click.echo(f"  Removed {len(diff.removed_track_ids)} tracks from state")

    # Download and upload new tracks
    for track in diff.new_tracks:
        click.echo(f"  Downloading: {track.artist} - {track.name}")
        try:
            file_path = download_track(
                track.spotify_url,
                output_dir,
                config.download.format,
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
            mapping_name=mapping.name,
            position=track.position,
            transcoded_sha256=result.transcoded_sha256,
            file_sha256=sha,
        )

        if config.sync.cleanup_downloads:
            file_path.unlink(missing_ok=True)

    # Build card content from all tracks in playlist order
    chapters: list[YotoChapter] = []
    for track in diff.all_tracks:
        sha = db.get_track_sha(track.track_id, mapping.name)
        if not sha:
            if verbose:
                click.echo(f"  Warning: no SHA for {track.name}, skipping from card")
            continue
        chapters.append(
            YotoChapter(
                title=f"{track.artist} - {track.name}",
                key=sha,
                duration=track.duration_ms // 1000,
            )
        )

    if not chapters:
        click.echo(f"  No chapters to write for '{mapping.name}'")
        return False

    click.echo(f"  Updating card with {len(chapters)} chapters")
    payload = YotoContentPayload(
        card_id=mapping.yoto_card_id,
        title=playlist.name,
        chapters=chapters,
    )
    yoto.update_card_content(payload)

    db.update_card_state(mapping.name, playlist.snapshot_id)
    click.echo(f"  '{mapping.name}' synced successfully")
    return True


def sync_all(
    config: AppConfig,
    yoto: YotoClient,
    db: StateDB,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """Sync all mappings. Returns number of failures."""
    failures = 0
    for mapping in config.mappings:
        click.echo(f"Syncing: {mapping.name}")
        try:
            ok = sync_mapping(mapping, config, yoto, db, dry_run=dry_run, verbose=verbose)
            if not ok:
                failures += 1
        except Exception as e:
            click.echo(f"  ERROR: {e}", err=True)
            failures += 1
    return failures
