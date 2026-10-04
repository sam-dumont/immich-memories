"""The moments a story can show, and the sample offered to the model.

A depicted moment is what one picture of a story would show; the pictures that can carry it are
its members. Everything here works on those moments before any model is asked: the capture
group's own representative, the five-minute capture spacing, the favourite/life/time sample
that keeps a request small, and the one competing nearby view per representative. The two-order
vote that decides which sampled moments tell the story lives in `editorial_story_vote`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from operator import itemgetter
from typing import Any

from immich_memories.analysis.subject_framing import SubjectVisibility

MIN_GAP_IN_CAPTURE_GROUP_SECONDS = 300


@dataclass
class DepictedChoice:
    """One depicted moment of a story and the pictures that can carry it."""

    key: str
    episode: str
    taken: str
    content: str
    primary: str
    alternatives: list[str] = field(default_factory=list)

    @property
    def members(self) -> list[str]:
        return [self.primary, *self.alternatives]


def spread_evenly(items: Sequence[Any], count: int) -> list[Any]:
    """Evenly spaced picks across a chronological list: beginning, middle and end before repeats."""
    if count >= len(items):
        return list(items)
    if count <= 0:
        return []
    if count == 1:
        return [items[len(items) // 2]]
    step = (len(items) - 1) / (count - 1)
    picks, seen = [], set()
    for i in range(count):
        index = round(i * step)
        if index not in seen:
            seen.add(index)
            picks.append(items[index])
    return picks


def company_relations(marker: str) -> frozenset[str]:
    people = marker.split("with: ", 1)[1] if "with: " in marker else ""
    return frozenset(relation.strip() for relation in people.split(",") if relation.strip())


def _nominate_new_relations(
    picked: list[DepictedChoice],
    choices: Sequence[DepictedChoice],
    companies: Mapping[str, frozenset[str]],
    *,
    protected: set[str],
    represented: frozenset[str],
) -> None:
    """Insert early relationship opportunities in place, without re-spacing the sample.

    Changing the sample's length or count moves unrelated stages throughout the story, so each
    nomination can replace only one nearby, non-favourite sample whose relationships stay covered.
    """
    positions = {c.key: index for index, c in enumerate(choices)}
    endpoints = {min(picked, key=lambda c: c.taken).key, max(picked, key=lambda c: c.taken).key}
    for candidate in choices:
        relations = companies[candidate.key]
        if candidate.key in protected or not relations - represented:
            continue
        if candidate not in picked:
            displaced = _replaceable_sample(
                picked,
                candidate,
                companies,
                protected=protected,
                endpoints=endpoints,
                positions=positions,
                relations=relations,
            )
            if displaced is None:
                continue
            picked[picked.index(displaced)] = candidate
        protected.add(candidate.key)
        represented |= relations


def _replaceable_sample(
    picked: Sequence[DepictedChoice],
    candidate: DepictedChoice,
    companies: Mapping[str, frozenset[str]],
    *,
    protected: set[str],
    endpoints: set[str],
    positions: Mapping[str, int],
    relations: frozenset[str],
) -> DepictedChoice | None:
    replaceable = [
        c
        for c in picked
        if c.key not in protected
        and companies[c.key]
        <= relations.union(*(companies[other.key] for other in picked if other != c))
    ]
    if not replaceable:
        return None
    return min(
        replaceable,
        key=lambda c: (
            c.key in endpoints,
            abs(positions[c.key] - positions[candidate.key]),
            positions[c.key],
        ),
    )


def _reach_for_motion(
    picked: list[DepictedChoice], moving: Sequence[DepictedChoice], grant: int
) -> None:
    """Add the moments that play which the sample's own ordering never reached.

    The sample is capped at three times the grant, so a story dense in favourites can fill it
    without ever offering a video. These are appended, never swapped in: no favourite is
    displaced and the spread already chosen is untouched. The reach is the story's grant,
    because that is the most moments the story can show, so one grant's worth of motion is the
    most that could change what it shows.
    """
    unreached = [c for c in moving if c not in picked]
    picked.extend(spread_evenly(unreached, min(grant, len(unreached))))


def shortlist_story_moments(
    choices: list[DepictedChoice],
    grant: int,
    *,
    starred: Callable[[DepictedChoice], bool],
    life: Callable[[str], bool],
    kind_of: Callable[[DepictedChoice], str] = lambda _c: "",
    plays: Callable[[DepictedChoice], bool] = lambda _c: False,
) -> list[DepictedChoice]:
    """Keep the favourite/motion/life/time sample, inserting early relationship opportunities.

    The chronological input is capped at three times the grant (floor six). A moment that
    plays is taken before a still that would otherwise fill its place, and motion the cap shut
    out is reached for afterwards: this is a video product. Relationship markers nominate
    opportunities; standing and audience admission come after.

    A story holding more favourites than the cap is sampled across its span rather than
    truncated: the earliest favourites of a long story are its first days, not the story.
    """
    limit = max(6, 3 * grant)
    if len(choices) <= limit:
        return choices
    stars = [c for c in choices if starred(c)]
    moving = [c for c in choices if c not in stars and plays(c)]
    lively = [c for c in choices if c not in stars + moving and any(life(a) for a in c.members)]
    rest = [c for c in choices if c not in stars + moving and c not in lively]
    picked = spread_evenly(stars, limit)
    picked.extend(spread_evenly(moving, limit - len(picked)))
    picked.extend(spread_evenly(lively, limit - len(picked)))
    picked.extend(spread_evenly(rest, limit - len(picked)))
    _reach_for_motion(picked, moving, grant)
    if len(stars) >= limit:
        return sorted(picked, key=lambda c: c.taken)

    companies = {c.key: company_relations(kind_of(c)) for c in choices}
    _nominate_new_relations(
        picked,
        choices,
        companies,
        protected={c.key for c in stars},
        represented=frozenset().union(*(companies[c.key] for c in stars)),
    )
    return sorted(picked, key=lambda c: c.taken)


def _capture_group_moments(
    units: Sequence[dict],
    *,
    quality: Callable[[str], float],
    flagged: Callable[[str], bool] = lambda _a: False,
    life: Callable[[str], bool] = lambda _a: True,
    plays: Callable[[dict], bool] = lambda _u: False,
    subject: Callable[[str], SubjectVisibility] = lambda _a: SubjectVisibility(0, 0.0),
    rank: Callable[[str, int, int], tuple] | None = None,
    withhold: Callable[[str], bool] | None = None,
    pixel_disqualified: Callable[[str], bool] = lambda _a: False,
) -> list[DepictedChoice]:
    """Without a model inventory a capture group is the moment; the favourite, else the best unflagged
    picture that shows life, carries it.

    ``pixel_disqualified`` names a picture whose line carries a pixel warning that only ranks a
    picture within its group (SOFT (blurry), DARK): never the owner's favourite. The ranking
    above always puts a clean sibling first when the group has one, so this only ever fires on
    the group's best candidate when every member carries it, which leaves the moment unfunded
    rather than shipping the one picture it has (#2049).

    Between two pictures that are otherwise equally entitled to the frame, the one that plays
    takes it: a second of the thing happening beats a sharper frame of it having happened. A
    video keeps losing on sharpness alone otherwise, because a video has no pixel facts.

    Sharpness is the last word only between frames that show the same thing. A frame where the
    named subject is a speck against the edge does not show what a frame of the same moment
    showing him does, so visibility is read first, and how much of the frame he covers breaks
    the tie between two frames that both show him. Pictures that name nobody all read zero,
    which leaves the order exactly as it was.

    A reader with no model behind it passes its own ``rank``, which reads capture facts
    instead of a caption and knows where a picture sits inside its burst.

    ``withhold`` names pictures an answer already banked about this library refuses: offering
    one costs the moment its slot, because the gate that refused it refuses it again. A moment
    whose every picture is withheld keeps them all: there is nothing left to offer instead, and
    the existing gates decide its fate exactly as they did before.
    """
    groups: dict[str, list[dict]] = {}
    for u in units:
        groups.setdefault(u.get("moment") or u["asset_id"], []).append(u)
    choices = []
    for moment, group in groups.items():
        members = _offerable(group, withhold)
        place = {u["asset_id"]: i for i, u in enumerate(sorted(members, key=itemgetter("taken")))}
        ordered = sorted(
            members,
            key=lambda u: (
                rank(u["asset_id"], place[u["asset_id"]], len(members))
                if rank is not None
                else (
                    not u.get("favourite"),
                    flagged(u["asset_id"]),
                    not life(u["asset_id"]),
                    not plays(u),
                    -subject(u["asset_id"]).rung,
                    -subject(u["asset_id"]).share,
                    -quality(u["asset_id"]),
                    u["taken"],
                )
            ),
        )
        primary = ordered[0]
        if not primary.get("favourite") and pixel_disqualified(primary["asset_id"]):
            continue
        choices.append(
            DepictedChoice(
                key=f"{moment}:cg",
                episode="",
                taken=min(u["taken"] for u in members),
                content="capture group",
                primary=primary["asset_id"],
                alternatives=[u["asset_id"] for u in ordered[1:]],
            )
        )
    return sorted(choices, key=lambda c: c.taken)


def _offerable(members: list[dict], withhold: Callable[[str], bool] | None) -> list[dict]:
    if withhold is None:
        return members
    kept = [u for u in members if not withhold(u["asset_id"])]
    return kept or members


def _instant(value):
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def capture_space_available(unit: Mapping[str, Any], occupied: Sequence[Mapping[str, Any]]) -> bool:
    """Apply the existing five-minute capture spacing to a source's own time and moment."""
    group, taken = unit.get("moment"), _instant(unit.get("taken"))
    if group is None or taken is None:
        return True
    return not any(
        other.get("moment") == group
        and (when := _instant(other.get("taken"))) is not None
        and abs((taken - when).total_seconds()) < MIN_GAP_IN_CAPTURE_GROUP_SECONDS
        for other in occupied
    )


def _spaced(
    chosen: Sequence[DepictedChoice],
    unit_by_asset: Mapping[str, Any],
    already: Sequence[Mapping[str, Any]] = (),
    *,
    among_choices: bool = True,
) -> list[DepictedChoice]:
    """Count or validate five-minute spacing, or filter against committed carriers only.

    Candidate comparison keeps nearby alternatives with ``among_choices=False``;
    physical capacity and the final cut still enforce their mutual exclusion.
    """
    occupied = list(already)
    kept: list[DepictedChoice] = []
    for c in sorted(chosen, key=lambda c: c.taken):
        unit = unit_by_asset[c.primary][1]
        if capture_space_available(unit, occupied):
            kept.append(c)
            if among_choices:
                occupied.append(unit)
    return kept


def nearby_picture_alternatives(
    primary_choices: Sequence[DepictedChoice],
    choices: Sequence[DepictedChoice],
    unit_by_asset: Mapping[str, Any],
    *,
    starred: Callable[[DepictedChoice], bool],
) -> list[DepictedChoice]:
    """One competing nearby picture per nonstarred representative, without deleting breadth."""
    used = {c.key for c in primary_choices}
    by_moment: dict[str, list[DepictedChoice]] = {}
    for choice in choices:
        moment = unit_by_asset[choice.primary][1].get("moment")
        if moment is not None:
            by_moment.setdefault(moment, []).append(choice)
    extras = []
    for primary in primary_choices:
        if starred(primary):
            continue  # the owner's chosen representative already leads this moment
        occupied = [unit_by_asset[primary.primary][1]]
        candidates = [
            c
            for c in by_moment.get(occupied[0].get("moment"), ())
            if c.key not in used
            and not capture_space_available(unit_by_asset[c.primary][1], occupied)
        ]
        if candidates:
            alternative = min(candidates, key=lambda c: (not starred(c), c.taken))
            used.add(alternative.key)
            extras.append(alternative)
    return extras
