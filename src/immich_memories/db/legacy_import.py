"""What one legacy importer did, in a shape the `store import` command can report."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImportOutcome:
    """One legacy source's import: records taken, records left alone, and why."""

    source: str
    imported: int
    skipped: int
    notes: tuple[str, ...] = ()
