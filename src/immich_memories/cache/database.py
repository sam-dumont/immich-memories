"""SQLite-based cache for video analysis results."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from immich_memories.cache.analysis_schema import ensure_cache_schema
from immich_memories.db.sqlite_files import connect_sqlite


class VideoAnalysisCache:
    """SQLite-based cache for video analysis results."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._ensure_db_exists()
        with self._get_connection() as conn:
            ensure_cache_schema(conn)

    def _ensure_db_exists(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        conn = connect_sqlite(
            self.db_path,
            private=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # =========================================================================
    # Core CRUD Methods
    # =========================================================================

    def clear_all(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM video_analysis")
            count = cursor.rowcount
            conn.commit()
            return count

    # =========================================================================
    # Query Methods (from DatabaseQueryMixin)
    # =========================================================================

    def get_stats(self) -> dict:
        with self._get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM video_analysis").fetchone()[0]

            with_hash = conn.execute(
                "SELECT COUNT(*) FROM video_analysis WHERE perceptual_hash IS NOT NULL"
            ).fetchone()[0]

            total_segments = conn.execute("SELECT COUNT(*) FROM video_segments").fetchone()[0]

            oldest = conn.execute("SELECT MIN(analysis_timestamp) FROM video_analysis").fetchone()[
                0
            ]

            newest = conn.execute("SELECT MAX(analysis_timestamp) FROM video_analysis").fetchone()[
                0
            ]

            return {
                "total_videos": total,
                "videos_with_hash": with_hash,
                "total_segments": total_segments,
                "oldest_analysis": oldest,
                "newest_analysis": newest,
                "database_size_bytes": (
                    self.db_path.stat().st_size if self.db_path.exists() else 0
                ),
            }
