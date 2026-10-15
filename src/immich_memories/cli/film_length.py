"""How long a film runs, sized on the pictures it may use.

A film is fitted to its material once the CLI has discovered some (`decide_duration`). Only
what every film's source admission keeps counts (`film_may_use`), and, when the run allows
them, the forwarded copies filling gaps in the film's camera timeline (`sized_film`,
`analysis.forwarded_copies_when_short`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from immich_memories.api.models import asset_of
from immich_memories.cli._helpers import print_info
from immich_memories.timeperiod import DateRange

if TYPE_CHECKING:
    from immich_memories.analysis.corpus.forwarded_fallback import CopyChecks, StandIns
    from immich_memories.config.loader import Config
    from immich_memories.planning.auto_duration import DurationDecision

logger = logging.getLogger(__name__)


def decide_duration(
    requested_duration: float | None,
    *,
    requested_source: str | None,
    preset_duration: float | None,
    memory_type: str | None,
    clips: list,
    photos: list | None,
    config: Config,
    accept_any_provenance: bool = False,
    stand_ins: frozenset[str] = frozenset(),
) -> DurationDecision:
    """Fit the film to its material, now that the CLI has discovered some.

    Only the pictures a film may use count (`film_may_use`): sized on forwarded copies the
    editor refuses, a birthday film asked for 245 s from material that filled 127. A forwarded
    copy standing in for a gap (`stand_ins`) is material too.
    """
    from immich_memories.analysis.corpus.validation import film_may_use
    from immich_memories.planning.auto_duration import (
        DURATION_FROM_DURATION_FLAG,
        decide_memory_duration,
    )

    camera = film_may_use(config, accept_any_provenance=accept_any_provenance)

    def usable(source) -> bool:
        return camera(source) or asset_of(source).id in stand_ins

    title_config = config.title_screens
    decision = decide_memory_duration(
        [clip for clip in clips if usable(clip)],
        [photo for photo in photos or [] if usable(photo)],
        requested_seconds=requested_duration,
        requested_source=requested_source or DURATION_FROM_DURATION_FLAG,
        preset_seconds=preset_duration,
        memory_type=memory_type,
        avg_clip_duration=config.analysis.optimal_clip_duration,
        photo_duration=config.photos.duration,
        title_duration=title_config.title_duration if title_config.enabled else 0.0,
        ending_duration=title_config.ending_duration if title_config.enabled else 0.0,
    )
    logger.info("%s memory. %s", memory_type or "Custom", decision.sentence())
    return decision


def copy_checks(client: Any, config: Config, pool: Sequence[Any]) -> CopyChecks:
    """The production checks a copy passes before it stands in: the duplicate review's own
    preview hash against the film's pictures, the preview for the collage check, and Immich's
    duplicate groups over the whole library. Each read happens only when a gap asks for it."""
    from functools import cache

    from immich_memories.analysis.corpus.forwarded_fallback import CopyChecks
    from immich_memories.analysis.preparation.thumbnail_hashes import CachedThumbnailHasher
    from immich_memories.analysis.runtime.ports import EditorialRuntimePorts
    from immich_memories.api.immich import ImmichAPIError

    preview = cache(EditorialRuntimePorts().preview_reader(client))
    bank = config.editorial.resolve_bank_root(config.cache.cache_path) / "structure-banks"
    hasher = CachedThumbnailHasher(bank / "thumbnail-hashes.sqlite", preview)

    def duplicate_groups() -> list[tuple[str, ...]]:
        try:
            return client.get_duplicate_groups()
        except (ImmichAPIError, OSError):
            # An older server or a key without the permission: the hash still checks.
            logger.info("Immich's duplicate groups are unavailable; copies are checked by hash")
            return []

    return CopyChecks(
        hash_of=hasher,
        preview_of=preview,
        originals=tuple(pool),
        duplicate_groups=duplicate_groups,
    )


def sized_film(
    requested_duration: float | None,
    *,
    requested_source: str | None,
    preset_duration: float | None,
    memory_type: str | None,
    clips: list,
    photos: list | None,
    config: Config,
    span: DateRange,
    windows: Sequence[DateRange] | None,
    accept_any_provenance: bool,
    checks: Callable[[Sequence[Any]], CopyChecks],
) -> tuple[DurationDecision, StandIns]:
    """The film's length, and the forwarded copies that fill gaps in its camera timeline, which
    the length counts as material and the run names (`analysis.forwarded_copies_when_short`).

    `windows` are the film's own when it has several; `span` stands for them when it has none.
    `checks` builds a copy's checks from the film's pictures.
    """
    from immich_memories.analysis.corpus.forwarded_fallback import StandIns, stand_in_copies

    pool = [*clips, *(photos or [])]
    stand_ins = (
        StandIns()
        if accept_any_provenance or not config.analysis.forwarded_copies_when_short
        else stand_in_copies(pool, config, windows=tuple(windows or (span,)), checks=checks(pool))
    )
    decision = decide_duration(
        requested_duration,
        requested_source=requested_source,
        preset_duration=preset_duration,
        memory_type=memory_type,
        clips=clips,
        photos=photos,
        config=config,
        accept_any_provenance=accept_any_provenance,
        stand_ins=stand_ins.ids,
    )
    _say_what_stands_in(stand_ins, pool)
    return decision, stand_ins


def _say_what_stands_in(stand_ins: StandIns, pool: Sequence[Any]) -> None:
    if stand_ins.ids:
        days = sorted(
            {
                asset_of(s).local_taken_at.date().isoformat()
                for s in pool
                if asset_of(s).id in stand_ins.ids
            }
        )
        print_info(
            f"Forwarded copies fill gaps in the camera timeline: {len(stand_ins.ids)} pictures on "
            f"{', '.join(days)} (analysis.forwarded_copies_when_short)"
        )
    if stand_ins.refused:
        print_info(
            f"{len(stand_ins.refused)} forwarded copies left out: a collage, or a copy of a "
            "picture the library holds"
        )
