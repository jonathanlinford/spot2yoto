# spot2yoto

Sync Spotify playlists to Yoto MYO cards.

## Setup

```bash
uv sync
spot2yoto config init
# Edit ~/.config/spot2yoto/config.yaml with your Spotify creds and mappings
spot2yoto auth yoto
spot2yoto auth spotify
```

## Usage

```bash
spot2yoto cards list              # List your MYO cards
spot2yoto sync all --dry-run      # Preview sync
spot2yoto sync all                # Sync all mappings
spot2yoto status                  # Show sync state
```

## Docker

```bash
docker compose run spot2yoto auth yoto
docker compose run spot2yoto sync all
```

Schedule with cron:
```
0 2 * * * cd /path/to/spot2yoto && docker compose run --rm spot2yoto sync all --quiet
```
