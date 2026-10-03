"""Prepare viewer-facing place labels while preserving source data for maps."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from immich_memories.home_country import known_home_country
from immich_memories.i18n import DEFAULT_LOCALE
from immich_memories.i18n_places import country_code, is_country, localise_place

if TYPE_CHECKING:
    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.processing.assembly_config import AssemblyClip, TitleScreenSettings


def apply_location_captions(
    clips: list[AssemblyClip],
    *,
    locale: str = DEFAULT_LOCALE,
    home_country: str | None = None,
    opening_title: str = "",
) -> list[AssemblyClip]:
    """Name cities on change; name a foreign country only when it adds new context."""
    captioned = []
    last_country = None
    for clip in clips:
        name = clip.location_name
        head, _, tail = (name or "").rpartition(", ")
        if is_country(tail):
            code = country_code(tail) or tail.casefold()
            already_titled = last_country is None and _title_names_country(
                opening_title, tail, locale
            )
            if code in (home_country, last_country) or already_titled:
                name = head
            last_country = code
        captioned.append(replace(clip, caption_location_name=localise_place(name, locale)))
    return captioned


def _title_names_country(title: str, country: str, locale: str) -> bool:
    from immich_memories.i18n_places import localise_country

    return any(
        re.search(rf"(?<!\w){re.escape(name)}(?!\w)", title, re.IGNORECASE)
        for name in (country, localise_country(country, locale))
    )


def resolve_caption_overlays(
    config: Config, *, add_date: bool | None, add_place: bool | None
) -> tuple[bool, bool]:
    """Whether a film is captioned with dates and with places: what the film asked, else the config.

    `defaults.add_date` and `defaults.add_place` are the one rule the web client, the CLI and
    automation start from, so no surface can quietly render without captions the others show.
    """
    return (
        config.defaults.add_date if add_date is None else add_date,
        config.defaults.add_place if add_place is None else add_place,
    )


def prepare_location_captions(
    params: GenerationParams,
    clips: list[AssemblyClip],
    *,
    title_settings: TitleScreenSettings | None = None,
) -> list[AssemblyClip]:
    """Use the actual opening title and known home country without scanning library history."""
    if not clips or not params.add_place_overlay or params.privacy_mode:
        return clips
    from immich_memories.processing.clip_caption import resolve_caption_locale

    locale = resolve_caption_locale(params.config.title_screens.locale)
    opening_title = ""
    if title_settings is not None and title_settings.enabled and title_settings.title_duration > 0:
        opening_title = title_settings.title_override or ""
        if title_settings.memory_type == "trip" and title_settings.trip_locations:
            opening_title = title_settings.trip_title_text or opening_title
    return apply_location_captions(
        clips,
        locale=locale,
        home_country=known_home_country(params.config),
        opening_title=opening_title,
    )


def locality_place_names(params: GenerationParams, clips: list[AssemblyClip]) -> list[AssemblyClip]:
    """Name each clip's city, town or village when geocoding is on.

    Immich names a picture after the nearest GeoNames town, which for a district that is not
    a municipality of its own is the neighbour's name. Home is asked about too: a location
    card names it when the film comes back from a trip. The country stays Immich's English
    one, so offline translation still recognises it; the
    locality arrives in the film's language. A privacy-mode cut is never asked about.
    """
    if params.privacy_mode:
        return clips
    from immich_memories.analysis.place_names import place_names_for

    resolved = {
        source.asset.id: exif.place_name
        for source in params.clips
        if (exif := source.asset.exif_info) is not None and exif.place_name
    }
    pending = [clip for clip in clips if clip.asset_id not in resolved]
    if not pending:
        return [
            replace(clip, location_name=_with_locality(resolved[clip.asset_id], clip.location_name))
            for clip in clips
        ]
    # The same resolver the film's pictures were named with (#1591), asked again here only for
    # a replay of a snapshot written before names travelled on the pictures; the store answers.
    places = place_names_for(params.config)
    localities = places.localities_at(
        (
            (clip.latitude, clip.longitude, (clip.location_name or "").rpartition(", ")[2])
            for clip in pending
        ),
        days=(clip.date for clip in pending),
    )
    pending_names = iter(localities)
    names = [
        resolved[clip.asset_id] if clip.asset_id in resolved else next(pending_names)
        for clip in clips
    ]
    return [
        replace(clip, location_name=_with_locality(locality, clip.location_name))
        if locality
        else clip
        for clip, locality in zip(clips, names, strict=True)
    ]


def _with_locality(locality: str, immich_name: str | None) -> str:
    country = (immich_name or "").rpartition(", ")[2]
    return f"{locality}, {country}" if is_country(country) else locality
