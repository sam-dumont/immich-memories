"""Prepare viewer-facing place labels while preserving source data for maps."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from immich_memories.i18n import DEFAULT_LOCALE
from immich_memories.i18n_places import is_country, localise_place

if TYPE_CHECKING:
    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.processing.assembly_config import AssemblyClip


def apply_location_captions(
    clips: list[AssemblyClip], *, locale: str = DEFAULT_LOCALE
) -> list[AssemblyClip]:
    """Localise every known place; timeline captioning hides only repeated labels."""
    return [
        replace(clip, caption_location_name=localise_place(clip.location_name, locale))
        for clip in clips
    ]


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
    params: GenerationParams, clips: list[AssemblyClip]
) -> list[AssemblyClip]:
    """Prepare place captions without home settings or a library-history scan."""
    if not params.add_place_overlay or params.privacy_mode:
        return clips
    from immich_memories.processing.clip_caption import resolve_caption_locale

    locale = resolve_caption_locale(params.config.title_screens.locale)
    return apply_location_captions(clips, locale=locale)


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

    # The same resolver the film's pictures were named with (#1591), asked again here only for
    # a replay of a snapshot written before names travelled on the pictures; the store answers.
    places = place_names_for(params.config)
    named = []
    for clip in clips:
        locality = None
        if clip.latitude is not None and clip.longitude is not None:
            locality = places.locality_at(clip.latitude, clip.longitude)
        named.append(
            replace(clip, location_name=_with_locality(locality, clip.location_name))
            if locality
            else clip
        )
    return named


def _with_locality(locality: str, immich_name: str | None) -> str:
    country = (immich_name or "").rpartition(", ")[2]
    return f"{locality}, {country}" if is_country(country) else locality
