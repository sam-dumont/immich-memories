"""Prepare viewer-facing place labels while preserving source data for maps."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

from immich_memories.analysis.familiar_places import (
    PlaceHistory,
    PlaceObservation,
    valid_coordinates,
)
from immich_memories.i18n import DEFAULT_LOCALE
from immich_memories.i18n_places import is_country, localise_place

if TYPE_CHECKING:
    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.processing.assembly_config import AssemblyClip

logger = logging.getLogger(__name__)


def _place_label(
    clip: AssemblyClip,
    history: PlaceHistory,
    home_area: PlaceHistory,
    home_country: str,
    locale: str,
) -> str | None:
    lat, lon = clip.latitude, clip.longitude
    if (
        lat is not None
        and lon is not None
        and (home_area.nearby(lat, lon) or history.is_familiar(lat, lon))
    ):
        return ""
    shown = clip.location_name
    if not shown or not home_country:
        return localise_place(shown, locale)
    # The comparison stays in English on purpose: `home_country` comes from
    # Immich's own EXIF, which is always English, and the translation happens
    # after the home country has been recognised and dropped.
    parts = shown.rsplit(", ", 1)
    if parts[-1].casefold() == home_country.casefold():
        return localise_place(parts[0], locale) if len(parts) == 2 else ""
    return localise_place(shown, locale)


def apply_location_captions(
    clips: list[AssemblyClip],
    history: PlaceHistory,
    *,
    home: tuple[float, float] | None = None,
    locale: str = DEFAULT_LOCALE,
) -> list[AssemblyClip]:
    """Hide home and recurring neighbourhoods; omit only the known home country.

    Country comes from GPS observations around the configured home, never a
    locale or a city-name guess. With no evidence, the original label survives.
    What survives is then read in the film's language.
    """
    home_rows = history.nearby(*home) if home else []
    countries = {row.country.strip() for row in home_rows if row.country.strip()}
    home_country = next(iter(countries)) if len(countries) == 1 else ""
    home_area = PlaceHistory([PlaceObservation(*home, date.min)] if home else [])
    return [
        replace(
            clip,
            caption_location_name=_place_label(clip, history, home_area, home_country, locale),
        )
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
    """Load history only when geographic captions are actually requested."""
    if not params.add_place_overlay or params.privacy_mode:
        return clips
    from immich_memories.analysis.familiar_place_cache import load_place_history

    history = PlaceHistory([])
    if params.client is not None:
        try:
            history = load_place_history(params.client, params.config.cache.cache_path)
        except Exception as error:
            logger.warning(
                "Familiar-place history unavailable (%s); retaining unverified place labels",
                type(error).__name__,
            )
    from immich_memories.processing.clip_caption import resolve_caption_locale

    trips = params.config.trips
    home = (trips.homebase_latitude, trips.homebase_longitude)
    locale = resolve_caption_locale(params.config.title_screens.locale)
    return apply_location_captions(
        clips, history, home=home if valid_coordinates(*home) else None, locale=locale
    )


def district_place_names(params: GenerationParams, clips: list[AssemblyClip]) -> list[AssemblyClip]:
    """Each clip's place under the district OpenStreetMap puts it in, when geocoding is on.

    Immich names a picture after the nearest GeoNames town, which for a district that is not
    a municipality of its own is the neighbour's name. Home is asked about too: a location
    card names it when the film comes back from a trip. The country stays Immich's English
    one, so the home-country drop and the offline translation still recognise it; the
    district arrives in the film's language. A privacy-mode cut is never asked about.
    """
    if params.privacy_mode:
        return clips
    from immich_memories.analysis.place_geocoder import district_of, place_geocoder_for

    places = place_geocoder_for(params.config)
    if places is None:
        return clips
    named = []
    for clip in clips:
        district = None
        if clip.latitude is not None and clip.longitude is not None:
            district = district_of(places.address(clip.latitude, clip.longitude))
        named.append(
            replace(clip, location_name=_with_district(district, clip.location_name))
            if district
            else clip
        )
    return named


def _with_district(district: str, immich_name: str | None) -> str:
    country = (immich_name or "").rpartition(", ")[2]
    return f"{district}, {country}" if is_country(country) else district
