"""Depth inside a story's moments, once pass 1/2 are done but the film is still short.

Split out of `editorial_story_carriers` (#2083): `CarrierAdmission` composes a `DepthFill`
and hands it everything it reads or mutates on the admitted cut, through the `DepthFillHost`
contract below, rather than this module reaching into `CarrierAdmission`'s own internals.

A film still short after every selection pass spends its free content seconds here, in the
story's funding order, round-robin across every funded story so one deep story cannot
swallow a round meant for its neighbours: first the depicted moments the inventory found and
no pick took, then further frames of the chosen moments. Each one is admitted only once it is
its own shot (`immich_memories.planning.distinct_shots`) and the look-alike check confirms it
shows something new; nothing unchecked, and no refused variant, ever fills a slot this way.
When distinct shots run out before the budget does, the film stops and says so in one line.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol

from immich_memories.analysis.editorial_picture_admission import PictureAdmission
from immich_memories.analysis.editorial_story_depth import depth_ladder, neighbours
from immich_memories.analysis.editorial_story_lookalike import LookAlikeCheck
from immich_memories.analysis.editorial_story_places import PlaceShares
from immich_memories.analysis.editorial_story_shortlist import DepictedChoice
from immich_memories.analysis.editorial_story_slots import PartitionedSlots
from immich_memories.analysis.editorial_story_standing import WEIGHED_STORY_WEIGHTS, StandingGate
from immich_memories.planning.distinct_shots import PICTURES_PER_BEAT, is_new_shot, is_own_beat

logger = logging.getLogger(__name__)


def _seconds_apart(taken: str, others: Sequence[str]) -> float:
    when = datetime.fromisoformat(taken)
    return min(
        (abs((when - datetime.fromisoformat(o)).total_seconds()) for o in others), default=0.0
    )


class DepthFillHost(Protocol):
    """Everything the depth fill reads or mutates on the `CarrierAdmission` it serves."""

    carriers: list[dict]
    slots: int
    parts: PartitionedSlots
    stories: Sequence[Mapping[str, Any]]
    chosen_by_story: dict[str, list[str]]
    places: PlaceShares
    choices_of: dict[str, list[DepictedChoice]]
    gate: StandingGate
    lookalike: LookAlikeCheck
    pictures: PictureAdmission
    _mechanical_picks: bool
    _unit_by_asset: Mapping[str, Any]
    _used_choice_keys: set[str]
    _content_budget_seconds: float | None
    _content_tolerance_seconds: float

    def free(self, asset: str) -> bool: ...
    def _crowds_its_place(self, s, choice, index, asset) -> bool: ...
    def _carrier_row(self, unit, family, s, choice, index, asset) -> dict: ...
    def _admit(self, s, choice, carrier, alternatives: list[str]) -> None: ...


class DepthFill:
    """One pass of the depth fill over a `CarrierAdmission`'s stories, shared state and all."""

    def __init__(self, host: DepthFillHost) -> None:
        self._host = host

    def run(self) -> None:
        if not self._host.lookalike.available:
            return
        self._deepen_round_robin()

    # -- budget -------------------------------------------------------------------

    def budget_met(self) -> bool:
        """Whether the film has spent the content budget the depth fill works against."""
        return self._depth_budget_met()

    def _depth_budget_met(self) -> bool:
        """Whether the depth fill should stop: content seconds against the real budget when
        one was sized, else the pass-1/pass-2 slot count a caller with no seconds budget
        still relies on (#2083)."""
        host = self._host
        if host._content_budget_seconds is None:
            return len(host.carriers) >= host.slots
        return (
            self._content_seconds()
            >= host._content_budget_seconds - host._content_tolerance_seconds
        )

    def _content_seconds(self) -> float:
        return sum(float(c.get("seconds") or 0.0) for c in self._host.carriers)

    def _log_depth_shortfall(self) -> None:
        """One line when distinct shots ran out before the budget did: an honest short film,
        not a silently repeated one (#2083)."""
        host = self._host
        if host._content_budget_seconds is None or self._depth_budget_met():
            return
        logger.info(
            "%d distinct shots, film runs %.1f s of %.1f s",
            len(host.carriers),
            self._content_seconds(),
            host._content_budget_seconds,
        )

    # -- the round-robin walk ------------------------------------------------------

    def _deepen_round_robin(self) -> None:
        """A film still short after every selection pass spends what room is left on further
        distinct shots, one at a time, round-robin across every story in funding order
        (#2083): draining one story's moments before its neighbours ever had a turn is how a
        person film kept filling the same handful of moments past the point of new material."""
        progressed = True
        while progressed and not self._depth_budget_met():
            progressed = False
            for index, s in enumerate(self._host.stories, 1):
                if self._depth_budget_met():
                    break
                if self._deepen_once(index, s):
                    progressed = True
        self._log_depth_shortfall()

    def _offerable(self, s) -> list[DepictedChoice]:
        """This story's moments, holding only the pictures that could carry a frame.

        The model ranks a moment's members, so its ladder walks the top three by position.
        Ranked by capture facts alone, position says little, and a picture that cannot carry
        a frame at all must not spend one of the moment's three rungs: an eight-picture
        moment was shipping two frames with five usable ones left behind. The spares that
        remain keep favourites first, then spread in capture time from the frames of the
        moment already in the cut.
        """
        host = self._host
        choices = host.choices_of[s["key"]]
        if not host._mechanical_picks:
            return choices
        host.gate.ensure([a for c in choices for a in c.members if host.free(a)])
        carried = {row["asset_id"] for row in host.carriers}
        offerable = []
        for c in choices:
            good = [
                a
                for a in c.members
                if a in carried or (host.free(a) and host.gate.stands(a, s["weight"], s["key"]))
            ]
            if not good:
                continue
            kept = [row["taken"] for row in host.carriers if row["depicted_moment"] == c.key]
            spare = sorted(
                (a for a in good if a not in carried),
                key=lambda a: (
                    not host._unit_by_asset[a][1].get("favourite"),
                    host._unit_by_asset[a][1].get("kind") not in ("video", "live-motion"),
                    -_seconds_apart(host._unit_by_asset[a][1]["taken"], kept),
                ),
            )
            members = [*(a for a in good if a in carried), *spare]
            offerable.append(replace(c, primary=members[0], alternatives=members[1:]))
        return offerable

    def _deepens(self, s) -> bool:
        """A story the cut already shows deepens when it is weighed, or when every era of the
        film speaks whatever its stories weigh (on this day, #2134)."""
        host = self._host
        weighed = (
            s["weight"] in WEIGHED_STORY_WEIGHTS
            or host.parts.every_era_speaks
            or self._is_a_big_event(s)
        )
        return weighed and bool(host.chosen_by_story[s["key"]])

    def _is_a_big_event(self, s) -> bool:
        """A story holding a capture group of two beats' worth of pictures or more: a day's event
        is several shots even when the story reads as a glimpse beside the rest (#2211)."""
        return s["weight"] != "none" and any(
            len(c.members) >= 2 * PICTURES_PER_BEAT for c in self._host.choices_of[s["key"]]
        )

    def _deepen_once(self, index: int, s) -> bool:
        host = self._host
        if self._depth_budget_met() or not self._deepens(s):
            return False
        held = sum(c["story_episode"] == s["key"] for c in host.carriers)
        host.places.widen(s["key"], held + host.slots - len(host.carriers))
        ladder = list(
            depth_ladder(
                self._offerable(s),
                chosen=host.chosen_by_story[s["key"]],
                used=host._used_choice_keys,
                group_of=lambda asset: host._unit_by_asset[asset][1].get("moment"),
                kept=[c["asset_id"] for c in host.carriers if c["story_episode"] == s["key"]],
            )
        )
        host.gate.ensure([asset for _choice, asset in ladder if host.free(asset)])
        for choice, asset in ladder:
            if self._depth_budget_met():
                break
            if not (host.free(asset) and host.gate.stands(asset, s["weight"], s["key"])):
                continue
            # A place-refused depth frame joins the same readmission ledger a place-refused
            # pass-1/2 carrier does (#2083), instead of a bare drop that `readmit` never saw.
            if host._crowds_its_place(s, choice, index, asset):
                continue
            family, unit = host._unit_by_asset[asset]
            row = host._carrier_row(unit, family, s, choice, index, asset)
            if not self._is_distinct_shot(s, row, choice):
                continue
            row = row | {"depth": True}
            if host.pictures.admits(row, cut=host.carriers, tier_of={}):
                continue
            host._used_choice_keys.add(choice.key)
            host._admit(s, choice, row, [])
            # One frame at a time: the next is spread from the frames kept, this one included.
            return True
        return False

    def _moment_sequence(self, s, choice: Any) -> list[str]:
        """Every picture of the moment, in capture order, whatever the offer has narrowed to."""
        host = self._host
        whole = next((c for c in host.choices_of[s["key"]] if c.key == choice.key), choice)
        return sorted(whole.members, key=lambda a: host._unit_by_asset[a][1]["taken"])

    def _is_distinct_shot(self, s, row: dict, choice: Any) -> bool:
        """Depth only ever adds a frame that is its own shot (#2083): the shared distinct-shot
        rule against every kept frame of the same capture group, and that the final review's
        own look-alike question still calls new against the story it would join."""
        host = self._host
        kept_in_moment = [c for c in host.carriers if c.get("moment") == row.get("moment")]
        if not (
            is_new_shot(row, kept_in_moment)
            or is_own_beat(row, kept_in_moment, self._moment_sequence(s, choice))
        ):
            return False
        # The look-alike question stays story-scoped, as it always was: an unchecked
        # (unhashed) neighbour anywhere in the story must still hold a brand-new moment
        # back, the same conservatism that keeps a thumbnail-less run from filling blind.
        kept_in_story = [c for c in host.carriers if c["story_episode"] == s["key"]]
        return host.lookalike.shows_something_new(
            s["key"], row, neighbours(row, kept_in_story), film=host.carriers
        )
