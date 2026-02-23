"""Tests for SQLite state database."""

from __future__ import annotations

from pathlib import Path

from spot2yoto.state import StateDB


class TestCardState:
    def test_get_snapshot_id_missing(self, db: StateDB):
        assert db.get_snapshot_id("no-card") is None

    def test_update_and_get(self, db: StateDB):
        db.update_card_state("card-1", "snap-abc")
        assert db.get_snapshot_id("card-1") == "snap-abc"

    def test_update_overwrites(self, db: StateDB):
        db.update_card_state("card-1", "snap-1")
        db.update_card_state("card-1", "snap-2")
        assert db.get_snapshot_id("card-1") == "snap-2"

    def test_get_card_state(self, db: StateDB):
        db.update_card_state("card-1", "snap-abc")
        state = db.get_card_state("card-1")
        assert state is not None
        assert state["mapping_name"] == "card-1"
        assert state["playlist_snapshot_id"] == "snap-abc"
        assert "last_synced_at" in state

    def test_get_card_state_missing(self, db: StateDB):
        assert db.get_card_state("no-card") is None

    def test_get_all_card_states(self, db: StateDB):
        db.update_card_state("card-1", "s1")
        db.update_card_state("card-2", "s2")
        states = db.get_all_card_states()
        assert len(states) == 2


class TestSyncState:
    def test_upsert_and_get(self, db: StateDB):
        db.upsert_track("t1", "card-1", 0, "sha-abc", "file-sha")
        sha = db.get_track_sha("t1", "card-1")
        assert sha == "sha-abc"

    def test_get_track_sha_missing(self, db: StateDB):
        assert db.get_track_sha("nope", "card-1") is None

    def test_get_track_sha_any(self, db: StateDB):
        db.upsert_track("t1", "card-1", 0, "sha-1")
        db.upsert_track("t1", "card-2", 0, "sha-1")
        assert db.get_track_sha_any("t1") == "sha-1"

    def test_get_track_sha_any_missing(self, db: StateDB):
        assert db.get_track_sha_any("nope") is None

    def test_get_all_tracks(self, db: StateDB):
        db.upsert_track("t1", "card-1", 0, "sha-1")
        db.upsert_track("t2", "card-1", 1, "sha-2")
        db.upsert_track("t3", "card-2", 0, "sha-3")
        tracks = db.get_all_tracks("card-1")
        assert len(tracks) == 2
        assert tracks[0]["spotify_track_id"] == "t1"
        assert tracks[1]["spotify_track_id"] == "t2"

    def test_upsert_updates_position(self, db: StateDB):
        db.upsert_track("t1", "card-1", 0, "sha-1")
        db.upsert_track("t1", "card-1", 5, "sha-2")
        tracks = db.get_all_tracks("card-1")
        assert tracks[0]["position"] == 5
        assert tracks[0]["transcoded_sha256"] == "sha-2"

    def test_remove_tracks(self, db: StateDB):
        db.upsert_track("t1", "card-1", 0, "sha-1")
        db.upsert_track("t2", "card-1", 1, "sha-2")
        db.remove_tracks("card-1", ["t1"])
        tracks = db.get_all_tracks("card-1")
        assert len(tracks) == 1
        assert tracks[0]["spotify_track_id"] == "t2"

    def test_remove_tracks_empty_list(self, db: StateDB):
        db.upsert_track("t1", "card-1", 0, "sha-1")
        db.remove_tracks("card-1", [])
        assert len(db.get_all_tracks("card-1")) == 1


class TestMediaCache:
    def test_get_missing(self, db: StateDB):
        assert db.get_cached_media("http://nope") is None

    def test_cache_and_get(self, db: StateDB):
        db.cache_media("http://img.jpg", "media-123", "cover")
        assert db.get_cached_media("http://img.jpg") == "media-123"

    def test_cache_overwrites(self, db: StateDB):
        db.cache_media("http://img.jpg", "old", "cover")
        db.cache_media("http://img.jpg", "new", "cover")
        assert db.get_cached_media("http://img.jpg") == "new"


class TestContextManager:
    def test_context_manager(self, tmp_path: Path):
        with StateDB(tmp_path / "ctx.db") as db:
            db.update_card_state("card-1", "snap")
            assert db.get_snapshot_id("card-1") == "snap"
