# spot2yoto

```
╔═════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                     ║
║                                                          ___                        ║
║                                ,-.----.                ,--.'|_                      ║
║                                \    /  \     ,---.     |  | :,'                     ║
║                     .--.--.    |   :    |   '   ,'\    :  : ' :                     ║
║                    /  /    '   |   | .\ :  /   /   | .;__,'  /                      ║
║                   |  :  /`./   .   : |: | .   ; ,. : |  |   |                       ║
║                   |  :  ;_     |   |  \ : '   | |: : :__,'| :                       ║
║                    \  \    `.  |   : .  | '   | .; :   '  : |__                     ║
║                     `----.   \ :     |`-' |   :    |   |  | '.'|                    ║
║                    /  /`--'  / :   : :     \   \  /    ;  :    ;                    ║
║                   '--'.     /  |   | :      `----'     |  ,   /                     ║
║                     `--'---'   `---'.|  ,----,          ---`-'                      ║
║                                  `---`.'   .' \                                     ║
║                                     ,----,'    |                                    ║
║                                     |    :  .  ;                                    ║
║                                     ;    |.'  /                                     ║
║                                     `----'/  ;                                      ║
║                                       /  ;  /                                       ║
║                                      ;  /  /-,                                      ║
║                                     /  /  /.`|                                      ║
║                                   ./__;      :                                      ║
║                                   |   :    .'                                       ║
║                                   ;   | .'   ___                                    ║
║                                   `---'    ,--.'|_                                  ║
║                                  ,---.     |  | :,'     ,---.                       ║
║                                 '   ,'\    :  : ' :    '   ,'\                      ║
║                         .--,   /   /   | .;__,'  /    /   /   |                     ║
║                       /_ ./|  .   ; ,. : |  |   |    .   ; ,. :                     ║
║                    , ' , ' :  '   | |: : :__,'| :    '   | |: :                     ║
║                   /___/ \: |  '   | .; :   '  : |__  '   | .; :                     ║
║                    .  \  ' |  |   :    |   |  | '.'| |   :    |                     ║
║                     \  ;   :   \   \  /    ;  :    ;  \   \  /                      ║
║                      \  \  ;    `----'     |  ,   /    `----'                       ║
║                       :  \  \               ---`-'                                  ║
║                        \  ' ;                                                       ║
║                         `--`                                                        ║
║                                                                                     ║
║        ♫ ♪  Spotify playlists ══════► Yoto MYO cards  ♪ ♫                           ║
║                                                                                     ║
║          ┌──────────┐    download    ┌──────────┐                                   ║
║          │ ░░░░░░░░ │   & upload     │ ┌──────┐ │                                   ║
║          │ ░ Spot ░ │ ═══════════>   │ │ MYO  │ │                                   ║
║          │ ░ ify  ░ │   chapters     │ │ Card │ │                                   ║
║          │ ░░░░░░░░ │   + artwork    │ └──────┘ │                                   ║
║          └──────────┘                └──────────┘                                   ║
║                                                                                     ║
╚═════════════════════════════════════════════════════════════════════════════════════╝
```

Creating custom Yoto players used to be a massive pain — manually downloading tracks, converting formats, uploading one by one, losing your place when playlists changed. No more. Just paste a Spotify playlist URL (or several) into a MYO card's description and let spot2yoto handle the rest. It downloads the audio, uploads it with cover art and chapters, and keeps everything in sync. Run it again whenever playlists change; it only syncs what's new.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- A [Spotify Developer](https://developer.spotify.com/dashboard) app (free, for playlist metadata)
- A Yoto account with MYO cards

## Quick Start

```bash
# 1. Build
# Assumes docker is running
docker compose build

# 2. Create config
docker compose run --rm spot2yoto config init
# Edit ~/.config/spot2yoto/config.yaml with your Spotify client_id and client_secret

# 3. Authenticate
docker compose run --rm spot2yoto auth yoto       # Prints a URL to visit for Yoto device code auth
docker compose run --rm spot2yoto auth spotify     # Opens browser for Spotify OAuth

# 4. Set up a card
# Go to the Yoto app, edit a MYO card's description, paste a Spotify playlist URL

# 5. Sync
docker compose run --rm spot2yoto sync --dry-run   # Preview what will happen
docker compose run --rm spot2yoto sync              # Download and upload tracks
```

## Commands

| Command | Description |
|---------|-------------|
| `auth yoto [NAME]` | Authenticate a Yoto account (default name: `default`) |
| `auth spotify` | Authenticate with Spotify (OAuth) |
| `auth status` | Show authentication status for all accounts |
| `cards list [--account NAME]` | List MYO cards (default: all accounts) |
| `cards show ID [--account NAME]` | Show full card details as JSON |
| `sync [--account NAME]` | Discover and sync cards with Spotify links (default: all accounts) |
| `sync --dry-run` | Preview sync without making changes |
| `status` | Show sync history |
| `config init` | Create default config file |

All commands are run via Docker:

```bash
docker compose run --rm spot2yoto <command>        # standard
docker compose run --rm spot2yoto -v <command>     # verbose
docker compose run --rm spot2yoto -q <command>     # quiet
```

## How Mapping Works

No config file mapping needed. Just put one or more Spotify playlist URLs anywhere in a [MYO card's description](https://my.yotoplay.com/my-cards/playlists):

```
This card has my kids' favorite songs!
https://open.spotify.com/playlist/37i9dQZF1DXaKIA8E7WcJj
https://open.spotify.com/playlist/4hOKQuZbraPDIfaGbM3lKI
```

spot2yoto scans all your MYO cards, finds any Spotify playlist URLs, validates they're reachable, merges the tracks (deduplicating across playlists), and syncs them to the card. Cover art is taken from the first playlist that has one.

## Deduplication

Five layers prevent unnecessary work:

1. **Playlist snapshot** — skips the entire card if none of its Spotify playlists have changed
2. **Per-track ID** — only downloads/uploads tracks that are new; duplicates across playlists on the same card are merged automatically
3. **Download cache** — downloaded MP3s are cached by track ID, so re-syncing or sharing a track across cards never re-downloads
4. **Cross-card upload reuse** — if a track was already uploaded for one card, its transcoded audio is reused for any other card that needs it
5. **File SHA256** — Yoto's API skips re-upload if the audio file already exists on their servers

## Scheduled Sync

```cron
0 2 * * * cd /path/to/spot2yoto && docker compose run --rm spot2yoto -q sync
```

## Docker Details

Config is mounted from `~/.config/spot2yoto/` so it's shared between containers. State and download cache use Docker volumes.

```yaml
volumes:
  - ~/.config/spot2yoto → /root/.config/spot2yoto   # config + tokens
  - spot2yoto-state     → /root/.local/share/spot2yoto  # sync state (SQLite)
  - spot2yoto-cache     → /root/.cache/spot2yoto        # download cache
```

## Config File

Located at `~/.config/spot2yoto/config.yaml`:

```yaml
yoto:
  client_id: "REDACTED_YOTO_CLIENT_ID"
spotify:
  client_id: "your-spotify-client-id"
  client_secret: "your-spotify-client-secret"
download:
  format: mp3
  output_dir: "~/.cache/spot2yoto/downloads"
sync:
  max_retries: 3
  transcode_poll_interval: 2
  transcode_poll_max_attempts: 60
```

## Spotify Developer App Setup

1. Go to https://developer.spotify.com/dashboard
2. Create an app (name: `spot2yoto`, description: anything)
3. Check **Web API**
4. Add redirect URI: `http://127.0.0.1:8888/callback`
5. Under **User Management**, add your Spotify account email
6. Copy Client ID and Client Secret into your config

## Local Development

If you'd rather run without Docker:

```bash
# Requires Python 3.11+ with uv and ffmpeg installed
uv sync
uv run spot2yoto sync
```
