"""Tests for SQLite busy_timeout on the cache's database connections.

WHY: Without busy_timeout, concurrent access (scheduler + UI + CLI) raises
'database is locked' immediately instead of retrying. Every connection comes from
the shared factory, which waits up to 30 seconds (#871). The store sets its own on
every connection; tests/store covers that.
"""

from __future__ import annotations

import pytest

from immich_memories.db.sqlite_files import BUSY_TIMEOUT_MS


@pytest.fixture
def temp_db(tmp_path):
    return tmp_path / "test.db"


class TestSqliteBusyTimeout:
    """All database connections must set the shared busy_timeout."""

    def test_video_analysis_cache_sets_busy_timeout(self, temp_db):
        from immich_memories.cache.database import VideoAnalysisCache

        cache = VideoAnalysisCache(temp_db)
        with cache._get_connection() as conn:
            result = conn.execute("PRAGMA busy_timeout").fetchone()
            assert result[0] == BUSY_TIMEOUT_MS
