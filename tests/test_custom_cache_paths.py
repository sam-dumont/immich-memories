"""Preview cleanup must operate on the configured cache."""

from unittest.mock import patch

from immich_memories.config_loader import Config
from immich_memories.ui.pages.step1_cache import _clear_preview_cache, _get_preview_cache_stats


def test_preview_stats_and_cleanup_follow_config_changes_at_call_time(tmp_path):
    first, second = (tmp_path / name for name in ("first", "second"))
    for path in (first, second):
        (path / "preview-cache").mkdir(parents=True)
        (path / "preview-cache" / "preview.mp4").write_bytes(b"preview")
    # WHY: the active configuration is the UI's boundary; no real user's cache is touched.
    with (
        patch("immich_memories.config.get_config") as active,
        patch(
            "immich_memories.ui.pages.step1_cache._PREVIEW_CACHE_DIR",
            first / "preview-cache",
            create=True,
        ),
    ):
        active.return_value = Config(cache={"directory": str(first)})
        assert _get_preview_cache_stats() == {"file_count": 1, "total_size_bytes": 7}
        active.return_value = Config(cache={"directory": str(second)})
        assert _clear_preview_cache() == 1
        assert _get_preview_cache_stats() == {"file_count": 0, "total_size_bytes": 0}
    assert (first / "preview-cache" / "preview.mp4").read_bytes() == b"preview"
    assert not (second / "preview-cache").exists()
