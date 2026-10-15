"""Privacy and anonymization helpers for video generation.

Extracted from generate.py — relocates GPS coordinates to a fake city,
anonymizes person names, and generates trip titles from preset params.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
from collections.abc import Iterable
from dataclasses import replace
from math import fsum, hypot

from immich_memories.api.person_expression import PersonExpression
from immich_memories.i18n_places import localise_place, place_label
from immich_memories.processing.assembly_config import AssemblyClip

logger = logging.getLogger(__name__)


_PRIVACY_FAKE_NAMES = [
    "Ada",
    "Bob",
    "Charlie",
    "Diana",
    "Eve",
    "Frank",
    "Grace",
    "Hank",
    "Iris",
    "Jack",
    "Kim",
    "Leo",
]
# WHY: real city coordinates so map tiles show a real place, not ocean
_PRIVACY_FAKE_CITIES = [
    ("Paris, France", 48.8566, 2.3522),
    ("Amsterdam, Netherlands", 52.3676, 4.9041),
    ("Barcelona, Spain", 41.3874, 2.1686),
    ("Copenhagen, Denmark", 55.6761, 12.5683),
    ("Lisbon, Portugal", 38.7223, -9.1393),
    ("Vienna, Austria", 48.2082, 16.3738),
    ("Prague, Czech Republic", 50.0755, 14.4378),
    ("Stockholm, Sweden", 59.3293, 18.0686),
]
# WHY: a relocated pin has to stay in the fake city's own area -- a quarter of a
# degree, roughly 25 km -- because a wide memory moved whole lands offshore, and
# a destination fuzzed into the sea reads worse than no map at all.
_PRIVACY_SPREAD_LIMIT_DEGREES = 0.25


def fake_names(names: Iterable[str | None]) -> dict[str, str]:
    """A consistent fake for each real name: distinct, and never one of the real names.

    The fakes come from a short list that holds common first names, so a hash alone can
    give a person their own name back, or two people the same one.
    """
    real = [name for name in dict.fromkeys(names) if name]
    taken = {part for name in real for part in (name, name.split()[0])}
    chosen: dict[str, str] = {}
    for name in real:
        # WHY: hashlib is deterministic across processes (hash() is not — PYTHONHASHSEED)
        start = int(hashlib.sha256(name.encode()).hexdigest(), 16) % len(_PRIVACY_FAKE_NAMES)
        for step in range(len(_PRIVACY_FAKE_NAMES)):
            fake = _PRIVACY_FAKE_NAMES[(start + step) % len(_PRIVACY_FAKE_NAMES)]
            if fake not in taken:
                break
        chosen[name] = fake
        taken.add(fake)
    return chosen


def pick_fake_city() -> tuple[str, float, float]:
    """Pick a deterministic fake city (same seed = same city every run)."""
    rng = random.Random(42)
    return _PRIVACY_FAKE_CITIES[rng.randint(0, len(_PRIVACY_FAKE_CITIES) - 1)]


def swap_names(text: str | None, fakes: dict[str, str]) -> str | None:
    """`text` with each real name, whole or by first name, replaced by its fake.

    A film's title is settled before it renders ("Kit · July 2025"), so swapping the
    names it was built from is not enough: the finished text carries them too.
    """
    if not text:
        return text
    spellings = fakes.copy()
    spellings |= {name.split()[0]: fake for name, fake in fakes.items() if " " in name}
    for real in sorted(spellings, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(real)}(?!\w)", spellings[real], text)
    return text


def preset_person_names(preset_params: dict) -> list[str]:
    """The names a title can read from the preset: display names, else the names asked for.

    With display names the other two hold person ids, which are scope, not text on screen.
    """
    display = preset_params.get("person_display_names")
    if display is not None:
        return [name for name in display.values() if name]
    names = list(preset_params.get("person_names", []))
    if preset_params.get("person_expression") is not None:
        names += PersonExpression.from_dict(preset_params["person_expression"]).leaf_values
    return names


def anonymize_preset_params(preset_params: dict, fakes: dict[str, str] | None = None) -> dict:
    """Swap every name a title can show, and move both ends of the trip."""
    fakes = fakes if fakes is not None else fake_names(preset_person_names(preset_params))
    result = preset_params.copy()
    if "person_display_names" in result:
        result["person_display_names"] = {
            identity: fakes.get(name, name) if name else ""
            for identity, name in result["person_display_names"].items()
        }
    else:
        if "person_names" in result:
            result["person_names"] = [fakes.get(name, name) for name in result["person_names"]]
        if result.get("person_expression") is not None:
            expression = PersonExpression.from_dict(result["person_expression"])
            result["person_expression"] = expression.map_leaves(
                lambda name: fakes.get(name, name)
            ).to_dict()
    fake_name, fake_lat, fake_lon = pick_fake_city()

    if result.get("home_lat") is not None:
        result["home_lat"] = fake_lat - 1.5  # Offset from city so route is visible
        result["home_lon"] = fake_lon - 1.0
    if result.get("location_name"):
        result["location_name"] = fake_name

    return result


def _relocation(clips: list[AssemblyClip]) -> tuple[float, float, float]:
    """Where the memory currently sits, and how much to shrink it to fit."""
    points = [
        (clip.latitude, clip.longitude)
        for clip in clips
        if clip.latitude is not None and clip.longitude is not None
    ]
    if not points:
        return 0.0, 0.0, 1.0
    centre_lat = fsum(lat for lat, _ in points) / len(points)
    centre_lon = fsum(lon for _, lon in points) / len(points)
    spread = max(hypot(lat - centre_lat, lon - centre_lon) for lat, lon in points)
    scale = (
        1.0 if spread <= _PRIVACY_SPREAD_LIMIT_DEGREES else _PRIVACY_SPREAD_LIMIT_DEGREES / spread
    )
    return centre_lat, centre_lon, scale


def anonymize_clips_for_privacy(
    clips: list[AssemblyClip],
) -> list[AssemblyClip]:
    """Move the whole memory onto the fake city, keeping the shape it had.

    Privacy mode used to blur the frames and then hand the map, the location
    cards and the place captions the real destination, which says where the
    family was more precisely than the footage ever did. The memory is moved as
    one piece -- its centre onto the fake city, every pin keeping its bearing
    and distance from that centre -- so the route still reads as a trip while
    the place is gone. The move is a function of the memory rather than of the
    run, so two renders of the same trip agree and repeated renders leave
    nothing to average away.

    Face blur and speech mute are handled separately by the assembler.
    """
    fake_name, city_lat, city_lon = pick_fake_city()
    centre_lat, centre_lon, scale = _relocation(clips)

    anonymized = []
    for clip in clips:
        # A clip that carried no place name must not gain one: an invented
        # caption changes what the render shows.
        name = fake_name if clip.location_name else None
        if clip.latitude is None or clip.longitude is None:
            anonymized.append(replace(clip, location_name=name))
            continue
        anonymized.append(
            replace(
                clip,
                latitude=city_lat + (clip.latitude - centre_lat) * scale,
                longitude=city_lon + (clip.longitude - centre_lon) * scale,
                location_name=name,
            )
        )
    return anonymized


def clip_location_name(exif, locale: str = "en") -> str | None:
    """The place one clip carries, as Immich recorded it.

    The default is English because this is the stored value: the map pins, the
    location cards and the clip overlay each translate it at the moment they
    draw it, and the home-country drop needs to compare against the English
    name Immich gave it.
    """
    if not exif:
        return None
    from immich_memories.analysis.places.names import shown_city

    return place_label(shown_city(exif), exif.country, locale)


def extract_trip_pins(
    assembly_clips: list[AssemblyClip],
    locale: str = "en",
) -> tuple[list[tuple[float, float]], list[str]]:
    """Unique GPS locations for map pins, and the name to label each one with.

    Both lists are built in one pass so they stay index-aligned: the renderer
    draws labels by position, so a name list de-duplicated by a different rule
    would caption every pin after the first repeat with the wrong place. A pin
    whose clip carried no place name holds its slot with an empty string.
    """
    seen: set[tuple[float, float]] = set()
    locations: list[tuple[float, float]] = []
    names: list[str] = []
    for clip in assembly_clips:
        if clip.latitude is not None and clip.longitude is not None:
            key = (round(clip.latitude, 2), round(clip.longitude, 2))
            if key not in seen:
                seen.add(key)
                locations.append((clip.latitude, clip.longitude))
                names.append(localise_place(clip.location_name, locale) or "")
    return locations, names


def generate_trip_title_text(
    preset_params: dict, locale: str = "en", *, capitals: bool = True
) -> str | None:
    """Generate trip title text from preset params, in capitals as the title card sets it."""
    from immich_memories.titles._trip_titles import generate_trip_title

    location_name = preset_params.get("location_name")
    trip_start = preset_params.get("trip_start")
    trip_end = preset_params.get("trip_end")

    if not location_name or not trip_start or not trip_end:
        return None

    kind = preset_params.get("location_kind") or None
    return generate_trip_title(
        location_name, trip_start, trip_end, locale=locale, kind=kind, capitals=capitals
    )
