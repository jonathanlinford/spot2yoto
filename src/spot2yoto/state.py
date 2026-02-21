"""SQLite state database for sync tracking."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE_DIR = Path("~/.local/share/spot2yoto").expanduser()
DEFAULT_STATE_PATH = DEFAULT_STATE_DIR / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS card_state (
    mapping_name TEXT PRIMARY KEY,
    playlist_snapshot_id TEXT NOT NULL,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    spotify_track_id TEXT NOT NULL,
    mapping_name TEXT NOT NULL,
    file_sha256 TEXT,
    transcoded_sha256 TEXT,
    position INTEGER NOT NULL,
    PRIMARY KEY (spotify_track_id, mapping_name)
);
"""


class StateDB:
    def __init__(self, path: Path | None = None):
        self._path = path or DEFAULT_STATE_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> StateDB:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- card_state ---

    def get_snapshot_id(self, mapping_name: str) -> str | None:
        row = self._conn.execute(
            "SELECT playlist_snapshot_id FROM card_state WHERE mapping_name = ?",
            (mapping_name,),
        ).fetchone()
        return row["playlist_snapshot_id"] if row else None

    def update_card_state(self, mapping_name: str, snapshot_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO card_state (mapping_name, playlist_snapshot_id, last_synced_at)
               VALUES (?, ?, ?)
               ON CONFLICT(mapping_name) DO UPDATE SET
                 playlist_snapshot_id = excluded.playlist_snapshot_id,
                 last_synced_at = excluded.last_synced_at""",
            (mapping_name, snapshot_id, now),
        )
        self._conn.commit()

    # --- sync_state ---

    def get_track_sha(self, track_id: str, mapping_name: str) -> str | None:
        row = self._conn.execute(
            "SELECT transcoded_sha256 FROM sync_state WHERE spotify_track_id = ? AND mapping_name = ?",
            (track_id, mapping_name),
        ).fetchone()
        return row["transcoded_sha256"] if row else None

    def get_track_sha_any(self, track_id: str) -> str | None:
        """Look up transcoded_sha256 for a track across ALL cards."""
        row = self._conn.execute(
            "SELECT transcoded_sha256 FROM sync_state WHERE spotify_track_id = ? LIMIT 1",
            (track_id,),
        ).fetchone()
        return row["transcoded_sha256"] if row else None

    def get_all_tracks(self, mapping_name: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sync_state WHERE mapping_name = ? ORDER BY position",
            (mapping_name,),
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_track(
        self,
        track_id: str,
        mapping_name: str,
        position: int,
        transcoded_sha256: str,
        file_sha256: str | None = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO sync_state
               (spotify_track_id, mapping_name, position, transcoded_sha256, file_sha256)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(spotify_track_id, mapping_name) DO UPDATE SET
                 position = excluded.position,
                 transcoded_sha256 = excluded.transcoded_sha256,
                 file_sha256 = COALESCE(excluded.file_sha256, sync_state.file_sha256)""",
            (track_id, mapping_name, position, transcoded_sha256, file_sha256),
        )
        self._conn.commit()

    def remove_tracks(self, mapping_name: str, track_ids: list[str]) -> None:
        if not track_ids:
            return
        placeholders = ",".join("?" for _ in track_ids)
        self._conn.execute(
            f"DELETE FROM sync_state WHERE mapping_name = ? AND spotify_track_id IN ({placeholders})",
            [mapping_name, *track_ids],
        )
        self._conn.commit()

    def get_card_state(self, mapping_name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM card_state WHERE mapping_name = ?",
            (mapping_name,),
        ).fetchone()
        return dict(row) if row else None

    def get_all_card_states(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM card_state").fetchall()
        return [dict(r) for r in rows]
