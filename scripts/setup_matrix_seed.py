"""Give a cell another cell's preparation, and none of its judgement.

Preparation depends on the host, the preparation tier and where the picture facts
come from. It does not depend on who reads afterwards, so the Mac cells that vary
only the reader would each pay for the same captions, heads and pixel facts and
publish that one number under every one of their names. `mac-local` measures it
once and the rest are seeded from its bank.

What must NOT come across is anything a reader decided. Per-cell caches exist
because the first real Mac run shared one and `mac-rules` published `mac-local`'s
verdicts as its own losses; seeding a reader's answers into a cell that exists to
compare readers would be that failure with extra steps. So the copy is followed
by a delete: every table in the cell's store (`store.db`, which `cache_pins` puts
in the cache directory) that holds a model's answer is emptied, a text-reading audience
hold with them, and the legacy files a pre-store bank kept beside it (`annotations.sqlite`,
`judgments.db`) are removed outright: nothing reads them but the one-time import.

    uv run python scripts/setup_matrix_seed.py <source cache> <destination cache>
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

# Where a bank keeps what a model said. `judgments` and its failure tables are
# the text gateway's; the episode and period tables are whole readings; the
# verdicts table is the cull's remembered buckets. Anything not listed here is a
# fact about a picture, which is the whole point of seeding.
VERDICT_TABLES = (
    "judgments",
    "text_completion_failures",
    "visual_judgments",
    "visual_completion_failures",
    "editorial_episode_readings",
    "editorial_period_insights",
    "editorial_verdicts",
    "editorial_episode_refusals",
    "audience_answers",
    "vote_bank_entries",
)

# Pre-store banks, and their sidecars: a copy would hand them to the cell's first-open import.
LEGACY_FILES = tuple(
    f"{name}{suffix}"
    for name in ("judgments.db", "annotations.sqlite")
    for suffix in ("", "-wal", "-shm")
)

# Each cell's store lives in its cache directory (`setup_matrix_plan.cache_pins`).
STORE_FILES = ("store.db",)


def strip_judgements(store: Path) -> list[str]:
    """Empty every verdict table an annotation store happens to carry, and name them.

    A table that was never created is not an error: which of them exist depends
    on what the source cell actually ran.
    """
    if not store.is_file():
        return []
    emptied = []
    with sqlite3.connect(store) as conn:
        present = {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in VERDICT_TABLES:
            if table in present:
                conn.execute(f"DELETE FROM {table}")  # noqa: S608 - a name from VERDICT_TABLES
                emptied.append(table)
        if "audience_holds" in present:
            # A detector's hold is a fact about the picture; a text model's is a reading.
            conn.execute("DELETE FROM audience_holds WHERE slot = 'text'")
            emptied.append("audience_holds (text)")
        conn.commit()
    return emptied


def seed_cache(source: Path, destination: Path) -> list[str]:
    """Copy `source` over `destination` and take every model answer back out of it.

    The destination is replaced rather than merged: a cell re-run has to start
    from the same preparation and no verdicts, or its second run would replay its
    first run's reading and report a selection that was never asked for.
    """
    if not source.is_dir():
        raise SystemExit(
            f"{source} does not exist, so this cell has no bank to seed from. The seed is the"
            " reference cell's cache for THIS library, under that library's own output"
            " directory: run that cell over this library once, or point --out at the run that"
            " already has it."
        )
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    for name in LEGACY_FILES:
        (destination / name).unlink(missing_ok=True)
    return [table for name in STORE_FILES for table in strip_judgements(destination / name)]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    emptied = seed_cache(Path(argv[0]).expanduser(), Path(argv[1]).expanduser())
    print(f"seeded {argv[1]} from {argv[0]}; emptied {', '.join(emptied) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
