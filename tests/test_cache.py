"""Tests for the video analysis cache."""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from immich_memories.cache.analysis_schema import CACHE_VERSION
from immich_memories.cache.database import VideoAnalysisCache
from tests.legacy_cache_db import write_legacy_cache_db


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def cache(temp_db_path):
    """Create a cache instance with a temporary database."""
    return VideoAnalysisCache(temp_db_path)


class TestVideoAnalysisCache:
    """Tests for VideoAnalysisCache."""

    def test_database_creation(self, cache, temp_db_path):
        """Database file should be created."""
        assert temp_db_path.exists()


class TestVideoAnalysisCacheEdgeCases:
    """Edge cases for cache operations."""

    def test_stats_empty_cache(self, cache):
        """Stats on empty cache return zeros."""
        stats = cache.get_stats()
        assert stats["total_videos"] == 0
        assert stats["total_segments"] == 0


def _rows(path: Path, query: str) -> list[tuple]:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(query).fetchall()


def _stamp(path: Path) -> int:
    return _rows(path, "PRAGMA user_version")[0][0]


class TestCacheVersionStamp:
    """The cache is stamped, never migrated: a finished ladder is adopted, anything else rebuilt."""

    def test_a_fresh_cache_is_stamped_with_every_table(self, cache, temp_db_path):
        tables = {name for (name,) in _rows(temp_db_path, "SELECT name FROM sqlite_master")}

        assert _stamp(temp_db_path) == CACHE_VERSION
        assert {"video_analysis", "video_segments", "hash_index", "video_metadata"} <= tables
        assert "asset_look_failures" in tables
        assert "pipeline_runs" not in tables

    def test_a_cache_the_ladder_finished_keeps_its_analysis(self, tmp_path):
        path = write_legacy_cache_db(tmp_path / "cache.db", version=25)
        _seed(path)

        VideoAnalysisCache(path)

        assert _stamp(path) == CACHE_VERSION
        assert _rows(path, "SELECT asset_id FROM video_analysis") == [("video-1",)]
        assert _rows(path, "SELECT run_id FROM pipeline_runs") == [("run-1",)]

    @pytest.mark.parametrize("version", [20, 24])
    def test_an_older_layout_is_rebuilt_and_the_history_left_for_the_import(
        self, tmp_path, version
    ):
        path = write_legacy_cache_db(tmp_path / "cache.db", version=version)
        _seed(path)

        VideoAnalysisCache(path)

        assert _stamp(path) == CACHE_VERSION
        assert _rows(path, "SELECT COUNT(*) FROM video_analysis") == [(0,)]
        assert _rows(path, "SELECT run_id FROM pipeline_runs") == [("run-1",)]

    def test_another_stamp_is_rebuilt(self, cache, temp_db_path):
        _seed(temp_db_path, run=False)
        with closing(sqlite3.connect(temp_db_path)) as conn:
            conn.execute("PRAGMA user_version = 99")

        VideoAnalysisCache(temp_db_path)

        assert _stamp(temp_db_path) == CACHE_VERSION
        assert _rows(temp_db_path, "SELECT COUNT(*) FROM video_analysis") == [(0,)]


def _seed(path: Path, *, run: bool = True) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT INTO video_analysis (asset_id, analysis_timestamp)"
            " VALUES ('video-1', '2026-01-01T00:00:00+00:00')"
        )
        if run:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, created_at) VALUES ('run-1', '2026-01-01')"
            )
        conn.commit()
