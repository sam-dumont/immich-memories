"""Config keys still read but no longer part of the documented config, each named when set.

Five kinds, all accepted through the 1.x line and gone in 2.0:

* tier-owned keys, which `tier` sets (`config/tiers.py` overrides whatever the file says);
* internal tuning knobs: the value is still used, but no operator should need it;
* merged keys, whose job another documented key does now (still honoured when set);
* moved keys, whose value is carried onto their replacement while that one is at its default;
* ignored keys: accepted so an old file still loads, and read by nothing.

A key counts as set when any source supplied it: config.yaml, an environment variable, a
saved setting or the deployment. Each warning names the key and what replaces it, never the
value, and is said once per process (the config loads several times per command).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from immich_memories.config.loader import Config

logger = logging.getLogger(__name__)

_REMOVAL = "it stops being read in 2.0"

# Set by the product tier: whatever a source says is replaced by the tier's value.
TIER_OWNED: tuple[str, ...] = (
    "editorial.reader",
    "editorial.preparation.tier",
    "editorial.laya_audience",
    "editorial.detectors_enabled",
)

# Still read, no longer documented: the default is the supported value.
INTERNAL: tuple[str, ...] = (
    "speech.vad_threshold",
    "speech.min_silence_ms",
    "analysis.live_photo_merge_window_seconds",
    "analysis.live_photo_min_clip_seconds",
    "photos.burst_window_seconds",
    "photos.burst_hash_threshold",
    "title_screens.map_move_min_seconds",
    "title_screens.map_move_max_seconds",
    "audio.music_block_seconds",
    "audio.max_music_blocks",
    "automation.burst_threshold",
    "editorial.preparation.batch_size",
    "editorial.people.seat_min_pictures",
    "editorial.people.seat_min_share",
    "editorial.people.big_story_density",
    "editorial.people.big_story_family_share",
    "editorial.laya_audience_threshold",
    "editorial.description_model",
    "editorial.head_versions",
    "editorial.pixel_producer_key",
    "analysis.optimal_clip_duration",
    "analysis.min_source_short_side",
    "analysis.max_album_assets",
    "title_screens.title_duration",
    "title_screens.month_divider_duration",
    "title_screens.ending_duration",
    "title_screens.month_divider_threshold",
    "llm.preflight_timeout_seconds",
)

# Still honoured when set, but another key does the job: key -> its replacement.
MERGED: dict[str, str] = {
    "musicgen.hemisphere": "trips.homebase_latitude",
    "ace_step.hemisphere": "trips.homebase_latitude",
}

# One switch for manual and automatic films: the old key's value lands on its replacement.
MOVED: dict[str, str] = {
    "automation.upload_to_immich": "upload.enabled",
    "automation.album_name": "upload.album_name",
}

# Read by nothing: key -> what to do instead.
IGNORED: dict[str, str] = {
    "musicgen.num_versions": "audio.max_regenerations decides how many takes a film gets",
    "ace_step.num_versions": "audio.max_regenerations decides how many takes a film gets",
}

UNDOCUMENTED: frozenset[str] = frozenset((*TIER_OWNED, *INTERNAL, *MERGED, *MOVED, *IGNORED))

_said: set[str] = set()


@contextmanager
def every_warning_said_again() -> Iterator[None]:
    """Say every warning again inside the block, then remember what was said before it."""
    said = _said.copy()
    _said.clear()
    try:
        yield
    finally:
        _said.update(said)


def _section(config: Any, key: str) -> tuple[Any, str]:
    *path, field = key.split(".")
    section = config
    for name in path:
        section = getattr(section, name)
    return section, field


def is_set(config: Config, key: str) -> bool:
    """Whether any source supplied this key, before the tier or a preset touched it."""
    section, field = _section(config, key)
    return field in section.model_fields_set


def _say_once(message: str, *args: object) -> None:
    text = message % args
    if text in _said:
        return
    _said.add(text)
    logger.warning(text)


def _advice(key: str) -> str:
    if key in TIER_OWNED:
        return f"the tier sets it, so remove it and choose tier: basic, gpu or full; {_REMOVAL}"
    if key in MERGED:
        return f"{MERGED[key]} decides it now; remove it, {_REMOVAL}"
    if key in MOVED:
        return f"use {MOVED[key]} instead, which this value is applied to; {_REMOVAL}"
    if key in IGNORED:
        return f"it is ignored: {IGNORED[key]}; remove it"
    return f"it is internal tuning with no supported use; remove it, {_REMOVAL}"


def warn_unsupported_keys(config: Config) -> list[str]:
    """Name every undocumented key a source set, with what replaces it; return the keys."""
    named = [key for key in sorted(UNDOCUMENTED) if is_set(config, key)]
    for key in named:
        _say_once("Config key %s is no longer supported: %s", key, _advice(key))
    return named


def apply_moved_keys(config: Config) -> None:
    """Carry each moved key's value onto its replacement while that one is at its default.

    "At its default", not "unset": older releases wrote every default into config.yaml, so an
    `upload.enabled: false` there says nothing, and reading it as a choice would quietly stop
    the automatic uploads `automation.upload_to_immich: true` asked for.
    """
    for old, new in MOVED.items():
        source, old_field = _section(config, old)
        target, new_field = _section(config, new)
        at_default = getattr(target, new_field) == type(target).model_fields[new_field].default
        if is_set(config, old) and at_default:
            setattr(target, new_field, getattr(source, old_field))
