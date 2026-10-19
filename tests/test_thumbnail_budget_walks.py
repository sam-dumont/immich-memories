"""The thumbnail budget costs what a run wrote, not what the cache holds.

On a 90k-file cache one full walk took 20-45 s, and a cold year film made 111
acquisition rounds, most for one or two pictures. Walking per round was ~44 min.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from immich_memories.cache import thumbnail_cache as thumbnail_cache_module
from immich_memories.cache.thumbnail_cache import ThumbnailCache
from tests.test_editorial_preparation import asset, preview, run, successful_ports


@pytest.fixture
def walks(monkeypatch):
    """Count full cache walks (every eviction pass stats the whole tree)."""
    real = thumbnail_cache_module.evict_to_budget
    seen: list[Path] = []

    def spy(directory, **kwargs):
        seen.append(directory)
        return real(directory, **kwargs)

    # WHY: the directory walk lives in evict_to_budget; counting its calls counts walks.
    monkeypatch.setattr(thumbnail_cache_module, "evict_to_budget", spy)
    return seen


def test_acquisition_rounds_walk_the_cache_once_per_run(tmp_path, walks):
    cache = ThumbnailCache(tmp_path / "thumbnails")
    cache.begin_run()
    calls: list = []

    for number in range(6):  # one picture per round, like a cold year film
        run(
            tmp_path,
            assets=[asset(f"r{number}a")],
            thumbnail_cache=cache,
            ports=successful_ports(calls),
            fetch_preview=lambda _id: preview(),
        )

    assert len(walks) == 1


def test_a_new_run_measures_the_cache_again(tmp_path, walks):
    cache = ThumbnailCache(tmp_path / "thumbnails")
    cache.begin_run()
    cache.enforce_budget()
    cache.begin_run()  # another process may have written since: resync
    cache.enforce_budget()

    assert len(walks) == 2


def test_puts_under_budget_never_walk_after_the_first_measurement(tmp_path, walks):
    cache = ThumbnailCache(tmp_path / "thumbnails")
    cache.begin_run()
    cache.enforce_budget()

    for number in range(450):  # past two of the old every-200-puts walks
        cache.put(f"asset-{number}", "preview", b"x" * 100)
    cache.put("asset-0", "preview", b"y" * 50)  # overwriting counts the difference

    assert len(walks) == 1
    assert cache.enforce_budget() == 0
    assert len(walks) == 1


def test_a_cache_pushed_over_budget_is_trimmed_oldest_first_sparing_this_run(tmp_path, walks):
    cache = ThumbnailCache(tmp_path / "thumbnails", max_size_mb=0.002)  # 2 KB
    old = cache.put("old", "preview", b"x" * 900)
    older = cache.put("older", "preview", b"x" * 900)
    stamp = time.time() - 7200
    os.utime(older, (stamp, stamp))
    os.utime(old, (stamp + 3600, stamp + 3600))
    cache.begin_run()
    cache.enforce_budget()  # measures: 1.8 KB, fits
    assert len(walks) == 1

    cache.put("mine", "preview", b"x" * 900)  # 2.7 KB tracked: over, walks and trims

    assert cache.get("older", "preview") is None
    assert cache.get("mine", "preview") is not None
    assert cache.get_stats()["total_size_bytes"] <= 2000


def test_a_run_that_overflows_with_its_own_files_does_not_walk_every_round(tmp_path, walks):
    cache = ThumbnailCache(tmp_path / "thumbnails", max_size_mb=0.001)
    cache.begin_run()
    for number in range(4):
        cache.put(f"asset-{number}", "preview", b"x" * 600)
        cache.enforce_budget()

    assert len(walks) <= 2  # nothing the run wrote can be freed; re-walking finds nothing


def test_clear_resets_the_tracked_size(tmp_path, walks):
    cache = ThumbnailCache(tmp_path / "thumbnails", max_size_mb=0.002)
    cache.begin_run()
    cache.put("a", "preview", b"x" * 900)
    cache.enforce_budget()
    cache.clear()
    cache.put("b", "preview", b"x" * 900)

    assert cache.enforce_budget() == 0
    assert cache.get("b", "preview") is not None
