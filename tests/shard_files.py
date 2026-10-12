"""Collect only the test files a CI shard lists (`make test-cov-xml TEST_SHARD=i/N`).

Handing pytest five hundred test files as arguments made each xdist worker's collection
about five times slower than walking the directory (90 to 250 s instead of about 60 on a
CI runner). With `--shard-files=LIST`, pytest walks `tests/` as it always does and skips,
before importing it, every test module the list leaves out. tests/conftest.py registers
these hooks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_KEEP = pytest.StashKey[frozenset[Path] | None]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--shard-files",
        default=None,
        help="a file listing the test files to collect, one path per line from the rootdir",
    )


def _kept(config: pytest.Config) -> frozenset[Path] | None:
    if _KEEP not in config.stash:
        listing = config.getoption("--shard-files")
        config.stash[_KEEP] = (
            frozenset(
                (config.rootpath / line).resolve()
                for line in Path(listing).read_text(encoding="utf-8").split()
            )
            if listing
            else None
        )
    return config.stash[_KEEP]


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    if not (collection_path.name.startswith("test_") and collection_path.suffix == ".py"):
        return None
    keep = _kept(config)
    if keep is None or collection_path.resolve() in keep:
        return None
    return True
