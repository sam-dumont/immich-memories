"""Isolated synthetic evidence and fresh stores for paid feature probes."""

import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from immich_memories.cache.judgment_cache import JudgmentCache
from immich_memories.db import StoreLocation, open_store
from immich_memories.db.bootstrap import URL_ENV


@contextmanager
def scratch_store():
    """Use an explicit location, ignoring any configured live database."""
    with TemporaryDirectory(prefix="imm-conformance-") as directory:
        root = Path(directory)
        store = open_store(location=StoreLocation(f"sqlite:///{root / 'store.db'}"))
        previous = os.environ.get(URL_ENV)
        os.environ[URL_ENV] = store.location.url
        try:
            yield root, store
        finally:
            JudgmentCache(store).flush()
            store.engine.dispose()
            if previous is None:
                os.environ.pop(URL_ENV, None)
            else:
                os.environ[URL_ENV] = previous


def race_assets():
    """A fictional race spread across eight hours, with enough prepared captions."""
    return [
        SimpleNamespace(
            id=f"race-{n}",
            file_created_at=datetime(2030, 6, 1, 9, tzinfo=UTC) + timedelta(minutes=20 * n),
            exif_info=None,
            people=[],
            is_favorite=False,
            is_video=False,
            duration_seconds=None,
            llm_description="Cyclists crossing a finish line in a cycling race",
        )
        for n in range(24)
    ]


@contextmanager
def scratch_judge(llm):
    """The production editorial judge with fresh evidence and answer artifacts."""
    from immich_memories.analysis.editorial_structure_io import StructureTextJudge
    from immich_memories.config_loader import Config

    with scratch_store() as (root, store):
        yield StructureTextJudge(Config(tier="full", llm=llm), root, judgments=store)
