"""Read the prepared caption corpus without migrating or modifying its database."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ThemeCaption(BaseModel):
    """A dated source witness; model answers can select it but cannot rewrite it."""

    model_config = ConfigDict(frozen=True)
    asset_id: str
    taken_at: datetime
    caption: str
    media_kind: str = "photo"
    people: tuple[str, ...] = ()
    place: str = ""


@dataclass(frozen=True)
class ThemeCorpus:
    rows: tuple[ThemeCaption, ...]
    total_assets: int


def caption_years(path: Path, *, producer: str) -> tuple[int, ...]:
    """Offer all prepared years, including photographs older than the first video."""
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            return tuple(
                int(row[0])
                for row in db.execute(
                    "SELECT DISTINCT substr(a.taken_at,1,4) FROM assets a "
                    "JOIN descriptions d USING(asset_id) WHERE d.model=? "
                    "AND length(trim(d.text))>0 ORDER BY 1",
                    (producer,),
                )
            )
    except (sqlite3.Error, OSError):
        return ()


def read_theme_captions(
    path: Path, *, producer: str, since: int = 1, until: int = 9999
) -> ThemeCorpus:
    """Read only the configured caption producer and report its actual coverage."""
    if not 1 <= since <= until <= 9999:
        raise ValueError("Theme years must satisfy 1 <= since <= until <= 9999")
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            people: dict[str, list[str]] = {}
            for asset_id, name in db.execute(
                "SELECT asset_id, person_name FROM asset_people WHERE person_name != ''"
            ):
                people.setdefault(asset_id, []).append(name)
            bounds = (f"{since:04d}-01-01", f"{until:04d}-12-31T99")
            total = db.execute(
                "SELECT COUNT(*) FROM assets WHERE taken_at BETWEEN ? AND ?", bounds
            ).fetchone()[0]
            records = db.execute(
                "SELECT a.asset_id,a.taken_at,a.media_kind,a.city,d.text FROM assets a "
                "JOIN descriptions d USING(asset_id) WHERE d.model=? "
                "AND a.taken_at BETWEEN ? AND ? AND length(trim(d.text))>0 "
                "ORDER BY a.taken_at,a.asset_id",
                (producer, *bounds),
            )
            rows = tuple(
                ThemeCaption(
                    asset_id=key,
                    taken_at=taken,
                    caption=text,
                    media_kind=kind or "photo",
                    people=tuple(sorted(set(people.get(key, [])))),
                    place=city or "",
                )
                for key, taken, kind, city, text in records
            )
    except (sqlite3.Error, OSError) as exc:
        raise ValueError(
            "Prepared captions unavailable; run prepare with the full tier first"
        ) from exc
    return ThemeCorpus(rows, total)
