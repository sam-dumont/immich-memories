"""Album candidates: a film for an album nobody has filmed, or one that has outgrown its film (#2229)."""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import date, datetime
from typing import Any

from immich_memories.automation.candidates import (
    CandidateCategory,
    Detection,
    MemoryCandidate,
    make_memory_key,
)

# album:{first}:{last}::{album id}:{pictures the film was made from}
_FILMED_KEY = re.compile(r"^album:[^:]*:[^:]*::(?P<id>[^:]+):(?P<count>\d+)$")
# Older manual films recorded datetimes, including the first/last capture time and timezone.
_MANUAL_SPAN = re.compile(
    r"^album:(?P<first>\d{4}-\d{2}-\d{2})(?:T[0-9:.+Z-]+)?:"
    r"(?P<last>\d{4}-\d{2}-\d{2})(?:T[0-9:.+Z-]+)?:$"
)


class AlbumDetector:
    """Proposes a new album, or a grown one, once per size it has been filmed at."""

    BASE_SCORE = 0.55
    MIN_NEW = 20
    MIN_GROWTH = 30
    GROWTH_RATIO = 1.5
    # A phone's "Recents", "Favorites" or "Live Photos" holds seven years of every picture, and
    # a film of that is no album's film. A moment, a trip or an event fits in half a year.
    MAX_SPAN_DAYS = 180

    def detect(
        self,
        albums: list[dict[str, Any]],
        user_id: str | None,
        generated_keys: Collection[str],
        today: date,
        *,
        include_shared: bool,
    ) -> Detection:
        """``albums`` are Immich's raw rows; ``user_id`` says which of them are yours."""
        filmed = _filmed_sizes(generated_keys)
        manual_spans = {
            (match["first"], match["last"])
            for key in generated_keys
            if (match := _MANUAL_SPAN.fullmatch(key))
        }
        candidates = []
        collections = 0
        skipped: set[str] = set()
        for album in albums:
            if not include_shared and not _is_mine(album, user_id):
                skipped.add("shared albums are excluded")
                continue
            count = album.get("assetCount") or 0
            first, last = _span(album, today)
            if (last - first).days > self.MAX_SPAN_DAYS:
                collections += count >= self.MIN_NEW
                skipped.add("albums span more than six months")
                continue
            before = filmed.get(album["id"])
            if before is None and (first.isoformat(), last.isoformat()) in manual_spans:
                # Made by hand, which keeps no id and no size: take it as filmed at this size.
                skipped.add("albums already have hand-made films")
                continue
            if not self._worth_a_film(count, before):
                skipped.add(
                    f"new albums need {self.MIN_NEW} pictures"
                    if before is None
                    else f"filmed albums need {self.MIN_GROWTH} more pictures and {self.GROWTH_RATIO:g} times their previous size"
                )
                continue
            candidates.append(self._candidate(album, count, first, last, before))
        return Detection(candidates, self._notes(bool(candidates), collections, skipped))

    @staticmethod
    def _notes(has_candidates: bool, collections: int, skipped: set[str]) -> tuple[str, ...]:
        notes: tuple[str, ...] = (
            (
                f"Left out {collections} album(s) that span more than six months: a collection, not a moment",
            )
            if collections
            else ()
        )
        if not has_candidates:
            reason = "; ".join(sorted(skipped)) if skipped else "the library has no albums"
            notes += (f"No album film: {reason}",)
        return notes

    def _worth_a_film(self, count: int, filmed_at: int | None) -> bool:
        if filmed_at is None:
            return count >= self.MIN_NEW
        return count - filmed_at >= self.MIN_GROWTH and count >= filmed_at * self.GROWTH_RATIO

    def _candidate(
        self, album: dict[str, Any], count: int, first: date, last: date, filmed_at: int | None
    ) -> MemoryCandidate:
        name = album.get("albumName") or "Unnamed album"
        reason = (
            f"Album '{name}' has grown from {filmed_at} to {count} pictures"
            if filmed_at is not None
            else f"New album '{name}', {count} pictures, never filmed"
        )
        return MemoryCandidate(
            memory_type="album",
            category=CandidateCategory.ALBUM,
            date_range_start=first,
            date_range_end=last,
            person_names=[],
            memory_key=make_memory_key(
                "album", first, last, discriminator=f"{album['id']}:{count}"
            ),
            score=self.BASE_SCORE,
            reason=reason,
            asset_count=count,
            extra_params={"album_id": album["id"]},
        )


def _filmed_sizes(generated_keys: Collection[str]) -> dict[str, int]:
    """Each album's picture count at its latest film, read back from the keys."""
    sizes: dict[str, int] = {}
    for key in generated_keys:
        match = _FILMED_KEY.match(key)
        if match:
            sizes[match["id"]] = max(sizes.get(match["id"], 0), int(match["count"]))
    return sizes


def _is_mine(album: dict[str, Any], user_id: str | None) -> bool:
    owner = album.get("ownerId") or next(
        (
            member.get("user", {}).get("id")
            for member in album.get("albumUsers") or []
            if member.get("role") == "owner"
        ),
        None,
    )
    # An owner Immich does not name cannot be proven someone else's.
    return owner is None or user_id is None or owner == user_id


def _span(album: dict[str, Any], today: date) -> tuple[date, date]:
    first = _day(album.get("startDate")) or _day(album.get("createdAt")) or today
    return first, _day(album.get("endDate")) or first


def _day(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
