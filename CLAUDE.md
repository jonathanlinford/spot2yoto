# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

spot2yoto syncs Spotify playlists to Yoto MYO cards. Users paste Spotify playlist URLs into MYO card descriptions, and the tool discovers them, downloads audio via yt-dlp (YouTube Music search), uploads to Yoto, and keeps cards in sync when playlists change.

## Build and run

Everything runs in Docker. Do not use `uv run` locally.

```bash
docker compose build                              # build image
docker compose run --rm spot2yoto sync -v          # run sync
docker compose run --rm spot2yoto --help            # any CLI command
docker compose run --rm spot2yoto auth yoto         # auth flow
docker compose run --rm spot2yoto cards list        # list cards
```

## Testing

Tests run inside Docker. Always validate changes by running the full test suite:

```bash
docker build --build-arg SETUPTOOLS_SCM_PRETEND_VERSION=0.1.0 -t spot2yoto-test .
docker run --rm --entrypoint "uv" spot2yoto-test run pytest -v
```

Run tests after any code change before considering the task complete.

## Architecture

**Sync flow** (`sync.py` orchestrates everything):
1. `discover_mappings()` — scan MYO card descriptions for Spotify URLs
2. `fetch_playlist()` — get tracks from Spotify, merge multiple playlists per card
3. Composite snapshot check — skip card if all playlist snapshot_ids unchanged
4. `compute_diff()` — determine new/removed tracks
5. `download_track()` — yt-dlp searches YouTube Music, caches MP3 by track_id
6. `upload_track()` — 4-step Yoto flow: get presigned URL → PUT file → poll transcode → get SHA256
7. Upload cover art + per-track album icons (cached in `media_cache` table)
8. `update_card_content()` — POST chapters with track references, cover image, icons

**Key modules:**
- `cli.py` — Click CLI (groups: `auth`, `cards`, `config`, `sync`, `status`)
- `yoto_client.py` — Yoto API client with auto token refresh, rate limit retry (capped at 60s)
- `yoto_auth.py` — OAuth device code flow for Yoto
- `spotify.py` — Spotify API via spotipy + yt-dlp audio download
- `state.py` — SQLite state DB (tables: `card_state`, `sync_state`, `media_cache`)
- `models.py` — Pydantic models for config, tokens, Spotify data, Yoto data
- `config.py` — YAML config loading from `~/.config/spot2yoto/config.yaml`

**Deduplication layers** (critical for avoiding redundant API calls):
1. Playlist snapshot — skip card entirely if unchanged
2. Track diff — only process new/removed tracks
3. Download cache — yt-dlp caches by track_id on disk
4. Cross-card upload reuse — `get_track_sha_any()` checks if track was uploaded for another card
5. File SHA256 — Yoto skips re-upload if identical file exists
6. Media cache — cover art and icon URLs → Yoto media IDs persisted in DB

## State and config paths

- **Config**: `~/.config/spot2yoto/config.yaml` (override: `SPOT2YOTO_CONFIG`)
- **Tokens**: `~/.config/spot2yoto/tokens/{account_name}.json`
- **State DB**: `~/.local/share/spot2yoto/state.db`
- **Download cache**: `~/.cache/spot2yoto/downloads/`

## Versioning

Version is derived from git tags via `setuptools-scm` + `hatch-vcs`. To release: `git tag v0.x.y && git push origin v0.x.y`. The CI workflow (`.github/workflows/release.yml`) builds and pushes multi-platform Docker images to ghcr.io on tag push.

## Exception hierarchy

```
Spot2YotoError
├── ConfigError
├── AuthError
├── YotoAPIError(status_code)  →  UploadError, TranscodeError
├── SpotifyError               →  DownloadError
└── SyncError
```
