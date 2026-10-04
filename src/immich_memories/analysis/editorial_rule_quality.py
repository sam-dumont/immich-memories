"""Which picture of a capture group is most entitled to carry the moment it shows.

Nothing here reads a caption or a model answer. The order is the product's: the owner's own
choice, then the frame that moves, then the people in it and how well the named one is shown,
then whether the pixels warn about it, then what the head saw, and only then the clock, with
the middle of a burst ahead of its ends, because the first frame of a burst is usually the one
taken before the thing happened.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from immich_memories.analysis.editorial_story_shortlist import DepictedChoice
from immich_memories.analysis.editorial_structure_budget import RESIDUAL_MIN
from immich_memories.analysis.subject_framing import framing_visibility

PIXEL_WARNINGS = ("SOFT (blurry)", "DARK", "BLOWN OUT")
# A sharpness far above the library's p10 floor does not deserve an ever-growing lead:
# past this multiple of the floor, one more stop of sharpness stops mattering.
SPARSE_SHARPNESS_CAP = 4.0


@dataclass(frozen=True)
class PictureFacts:
    """What a CPU-only install knows about one picture, and where it sits in its group."""

    favourite: bool
    motion: bool
    known_people: int
    subject_rung: int
    subject_share: float
    pixel_warning: bool
    people_in_frame: bool
    place: int
    of: int
    taken: str
    banked_lead: bool = False


def picture_facts(
    asset: Any,
    *,
    line: str,
    place: int,
    of: int,
    residual: float | None,
    banked_lead: bool = False,
) -> PictureFacts:
    """Read one picture's facts off the asset, its annotation line and its motion residual.

    The line is the full one, flags and people included: the head labels and the
    subject-framing observation a rules reader needs are rendered there and stripped from the
    line the story reader sees.

    `banked_lead` is the one thing a rules reader cannot work out for itself: that a banked
    reading named it for its episode. On a library nothing has read it is false and the order is
    the one this reader has always produced.
    """
    visibility = framing_visibility(line)
    return PictureFacts(
        favourite=bool(asset.is_favorite),
        motion=bool(asset.is_video) or (residual is not None and residual >= RESIDUAL_MIN),
        known_people=len(asset.people or ()) or len(asset.faces or ()),
        subject_rung=visibility.rung,
        subject_share=visibility.share,
        pixel_warning=any(warning in line for warning in PIXEL_WARNINGS),
        people_in_frame="people=" in line and "people=none" not in line,
        place=place,
        of=of,
        taken=asset.file_created_at.isoformat(),
        banked_lead=banked_lead,
    )


def representative_key(facts: PictureFacts) -> tuple:
    """Sort key, smallest first."""
    return (
        not facts.favourite,
        # A picture its episode's reading named carries the moment.
        not facts.banked_lead,
        not facts.motion,
        -facts.known_people,
        # A named face that is a speck against the frame's edge does not show the person a
        # frame of the same moment showing him does. Pictures naming nobody all read zero.
        -facts.subject_rung,
        -facts.subject_share,
        facts.pixel_warning,
        not facts.people_in_frame,
        # Distance from the middle of the burst, doubled so it stays whole.
        abs(2 * facts.place - (facts.of - 1)),
        facts.taken,
    )


def rule_representative_rank(
    assets: Mapping[str, Any],
    lines: Mapping[str, str],
    residuals: Mapping[str, Mapping[str, Any]],
    *,
    leads: Collection[str] = (),
):
    """The rank a no-model reader gives one picture of a group of ``of`` pictures.

    `leads` are the pictures a banked episode reading named: what earlier model answers about
    this library say. It is empty on a library nothing has read.
    """

    def rank(asset_id: str, place: int, of: int) -> tuple:
        return representative_key(
            picture_facts(
                assets[asset_id],
                line=lines.get(asset_id, ""),
                place=place,
                of=of,
                residual=(residuals.get(asset_id) or {}).get("residual"),
                banked_lead=asset_id in leads,
            )
        )

    return rank


@dataclass(frozen=True)
class QualityFacts:
    """What a sparse week's best-picture pick needs to know about one candidate.

    This is a different question than `PictureFacts`: no reader has named a lead or
    weighed a burst here, there is no occasion to be representative of yet, so the
    hard filters below (never a screenshot, document, held-back, warned-about or
    under-sharp frame) stand in for the owner's own first pass over the week.
    """

    disqualified: bool
    faces_present: bool
    sharpness_ratio: float
    brightness: float
    distance_from_midweek: float
    taken: str


def quality_facts(
    asset: Any,
    *,
    line: str,
    heads: Mapping[str, str],
    standing: int,
    sharpness: float,
    sharpness_floor: float,
    brightness: float,
    distance_from_midweek: float,
    never_auto: bool,
) -> QualityFacts:
    """Read one candidate's hard filters and its sort facts for its week's best pick.

    `heads` are the raw detector labels (`"doc_docling"`, `"screen"`), the same
    vocabulary `RuleStructureReader.standing` reads them in, not the renamed ones an
    annotation line prints for a person.
    """
    screenshot = heads.get("screen", "no") != "no"
    document = heads.get("doc_docling", "photograph") != "photograph"
    warned = any(warning in line for warning in PIXEL_WARNINGS) or "rotated" in line.lower()
    disqualified = (
        warned
        or standing < 1
        or sharpness < sharpness_floor
        or screenshot
        or document
        or never_auto
    )
    ratio = min(sharpness / sharpness_floor, SPARSE_SHARPNESS_CAP) if sharpness_floor > 0 else 0.0
    return QualityFacts(
        disqualified=disqualified,
        faces_present=bool(asset.people) or ("people=" in line and "people=none" not in line),
        sharpness_ratio=ratio,
        brightness=brightness,
        distance_from_midweek=distance_from_midweek,
        taken=asset.file_created_at.isoformat(),
    )


def quality_key(facts: QualityFacts) -> tuple:
    """Sort key, smallest first; a disqualified candidate never wins its week."""
    return (
        facts.disqualified,  # False sorts first: a clean candidate always beats a hard filter
        not facts.faces_present,
        -facts.sharpness_ratio,
        abs(facts.brightness - 128),
        facts.distance_from_midweek,
        facts.taken,
    )


def promote_quality_choice(
    eligible: Sequence[DepictedChoice], asset_id: str | None
) -> list[DepictedChoice]:
    """Surface the picture `read_story` already chose as a sparse week's best picture.

    The moment that carries it is made primary by it and ordered first; every other
    moment of the story follows, unchanged. Nothing here asks a fresh question: the
    quality ranking already ran once, in `read_story`, over the week's whole pool.
    """
    if not asset_id:
        return list(eligible)
    surfaced, rest = [], []
    for choice in eligible:
        if asset_id not in choice.members:
            rest.append(choice)
            continue
        if choice.primary != asset_id:
            choice = replace(
                choice, primary=asset_id, alternatives=[a for a in choice.members if a != asset_id]
            )
        surfaced.append(choice)
    return [*surfaced, *rest]
