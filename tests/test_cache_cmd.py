"""Tests for cache CLI commands (stats, export, import, backup)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, call, patch

from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config_loader import Config

# WHY: these are the database boundaries — commands import them inline
_CACHE_CLS = "immich_memories.cache.database.VideoAnalysisCache"
_SCORE_CACHE_CLS = "immich_memories.cache.asset_score_cache.AssetScoreCache"
_GET_CONFIG = "immich_memories.config.get_config"


def _invoke(args: list[str]) -> object:
    """Invoke the CLI with mocked config and init_config_dir."""
    runner = CliRunner()
    with (
        TemporaryDirectory() as temporary,
        patch("immich_memories.cli.init_config_dir"),
        patch(
            "immich_memories.cli.get_config",
            return_value=Config(cache={"database": str(Path(temporary) / "cache.db")}),
        ),
    ):
        return runner.invoke(main, args, catch_exceptions=False)


def _make_mock_db(
    *,
    stats: dict | None = None,
    rows: list[dict] | None = None,
) -> MagicMock:
    """Build a mock VideoAnalysisCache with sensible defaults."""
    mock_db = MagicMock()

    if stats is not None:
        mock_db.get_cache_stats.return_value = stats

    if rows is not None:
        mock_db.all_scores.return_value = rows

    return mock_db


class TestCacheStats:
    def test_renders_table_with_stats(self):
        stats = {
            "total": 42,
            "assets": 37,
            "by_type": {"VIDEO": 30, "IMAGE": 12},
            "with_llm": 15,
            "oldest": "2025-01-01 10:00:00",
            "newest": "2026-03-19 08:00:00",
        }
        mock_db = _make_mock_db(stats=stats)

        with patch(_SCORE_CACHE_CLS, return_value=mock_db), patch(_GET_CONFIG):
            result = _invoke(["cache", "stats"])

        assert result.exit_code == 0
        mock_db.get_cache_stats.assert_called_once()
        assert "42" in result.output
        assert "15" in result.output

    def test_renders_empty_cache(self):
        stats = {
            "total": 0,
            "assets": 0,
            "by_type": {},
            "with_llm": 0,
            "oldest": None,
            "newest": None,
        }
        mock_db = _make_mock_db(stats=stats)

        with patch(_SCORE_CACHE_CLS, return_value=mock_db), patch(_GET_CONFIG):
            result = _invoke(["cache", "stats"])

        assert result.exit_code == 0
        # None dates render as em-dash
        assert "\u2014" in result.output


class TestCacheExport:
    def test_writes_json_file(self, tmp_path):
        rows = [
            {"asset_id": "abc-123", "asset_type": "VIDEO", "combined_score": 0.85},
            {"asset_id": "def-456", "asset_type": "IMAGE", "combined_score": 0.42},
        ]
        mock_db = _make_mock_db(rows=rows)
        out_file = tmp_path / "export.json"

        with patch(_SCORE_CACHE_CLS, return_value=mock_db), patch(_GET_CONFIG):
            result = _invoke(["cache", "export", str(out_file)])

        assert result.exit_code == 0
        data = json.loads(out_file.read_text())
        assert len(data) == 2
        assert data[0]["asset_id"] == "abc-123"
        assert "Exported 2" in result.output

    def test_export_empty_cache(self, tmp_path):
        mock_db = _make_mock_db(rows=[])
        out_file = tmp_path / "empty.json"

        with patch(_SCORE_CACHE_CLS, return_value=mock_db), patch(_GET_CONFIG):
            result = _invoke(["cache", "export", str(out_file)])

        assert result.exit_code == 0
        data = json.loads(out_file.read_text())
        assert data == []
        assert "Exported 0" in result.output


class TestCacheImport:
    def test_imports_scores_from_json(self, tmp_path):
        records = [
            {
                "asset_id": "abc-123",
                "asset_type": "VIDEO",
                "metadata_score": 0.7,
                "combined_score": 0.85,
                "llm_interest": 0.9,
                "llm_quality": 0.8,
                "llm_emotion": "joy",
                "llm_description": "Birthday party",
                "model_version": "v1",
            },
            {
                "asset_id": "def-456",
                "asset_type": "IMAGE",
                "metadata_score": 0.3,
                "combined_score": 0.42,
            },
        ]
        in_file = tmp_path / "import.json"
        in_file.write_text(json.dumps(records))

        mock_db = MagicMock()

        with patch(_SCORE_CACHE_CLS, return_value=mock_db), patch(_GET_CONFIG):
            result = _invoke(["cache", "import", str(in_file)])

        assert result.exit_code == 0
        assert mock_db.save_asset_score.call_count == 2
        assert "Imported 2" in result.output

        # Verify first call got all fields
        first_call = mock_db.save_asset_score.call_args_list[0]
        assert first_call == call(
            asset_id="abc-123",
            asset_type="VIDEO",
            metadata_score=0.7,
            combined_score=0.85,
            llm_interest=0.9,
            llm_quality=0.8,
            llm_emotion="joy",
            llm_description="Birthday party",
            llm_category=None,
            model_version="v1",
        )

        # Verify second call uses defaults for missing optional fields
        second_call = mock_db.save_asset_score.call_args_list[1]
        assert second_call == call(
            asset_id="def-456",
            asset_type="IMAGE",
            metadata_score=0.3,
            combined_score=0.42,
            llm_interest=None,
            llm_quality=None,
            llm_emotion=None,
            llm_description=None,
            llm_category=None,
            model_version=None,
        )

    def test_import_empty_file(self, tmp_path):
        in_file = tmp_path / "empty.json"
        in_file.write_text("[]")

        mock_db = MagicMock()

        with patch(_SCORE_CACHE_CLS, return_value=mock_db), patch(_GET_CONFIG):
            result = _invoke(["cache", "import", str(in_file)])

        assert result.exit_code == 0
        mock_db.save_asset_score.assert_not_called()
        assert "Imported 0" in result.output


class TestCacheBackup:
    def test_backs_up_the_analysis_cache_into_a_readable_file(self, tmp_path):
        from immich_memories.cache.database import VideoAnalysisCache

        cache_db = tmp_path / "cache.db"
        VideoAnalysisCache(cache_db)
        with sqlite3.connect(cache_db) as conn:
            conn.execute(
                "INSERT INTO video_analysis (asset_id, analysis_timestamp)"
                " VALUES ('video-1', '2026-01-01T00:00:00+00:00')"
            )
        out_file = tmp_path / "backup.db"

        # WHY: the CLI root makes ~/.immich-memories and loads the user's config; this test
        # names its own cache file instead.
        with (
            patch("immich_memories.cli.init_config_dir"),
            patch(
                "immich_memories.cli.get_config",
                return_value=Config(cache={"database": str(cache_db)}),
            ),
        ):
            result = CliRunner().invoke(main, ["cache", "backup", str(out_file)])

        assert result.exit_code == 0, result.output
        assert "backed up" in result.output
        with sqlite3.connect(out_file) as conn:
            assert conn.execute("SELECT asset_id FROM video_analysis").fetchall() == [("video-1",)]
