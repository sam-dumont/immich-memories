"""Shared picture admission for draft selection, refinement and later replacements."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from operator import itemgetter
from typing import Any, Protocol

from immich_memories.analysis.editorial_final_hash_review import (
    ScenePrint,
    review_cut_by_cached_hashes,
)
from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
from immich_memories.analysis.editorial_shareability import allowed, unit_members
from immich_memories.analysis.editorial_story_replies import film_close_family
from immich_memories.analysis.editorial_story_shortlist import capture_space_available
from immich_memories.analysis.editorial_story_standing import StandingGate
from immich_memories.analysis.editorial_structure_material import Material
from immich_memories.analysis.favourite_law import favourites_by_moment, stands_for_its_moment

# What a worthiness tier means to the standing gate, which asks in weight words.
WEIGHT_OF_TIER = {"remarkable": "major", "maybe": "minor", "background": "glimpse"}


class StandsAlone(Protocol):
    """The production standing gate, as this pass uses it."""

    def ensure(self, assets: Sequence[str], needs: Mapping[str, int] | None = None) -> None: ...

    def needs(self, asset: str, weight: str, story_key: str = "") -> int: ...

    def stands(self, asset: str, weight: str, story_key: str = "") -> bool: ...

    def rejected_motion(self, asset: str) -> bool: ...

    def has_required_context(self, asset: str, weight: str, story_key: str) -> bool: ...


class ShowsToTheAudience(Protocol):
    """The production audience gate, as this pass uses it."""

    def verdict_of(self, unit: Mapping[str, Any]) -> str: ...

    def prefetch(self, units: Sequence[Mapping[str, Any]], *, batch: int) -> None: ...


@dataclass(frozen=True)
class GateRefusal:
    """One shot the gates took out of the draft, and which gate took it."""

    asset_id: str
    story: str
    rule: str
    detail: str
    moment: str = ""


@dataclass(frozen=True)
class PictureAdmission:
    """Prepare a proposed picture and check its standing, audience, spacing and repetition."""

    standing: StandsAlone
    audience: ShowsToTheAudience | None
    thumbnail_hash: Callable[[str], str | None] | None
    audience_name: str = "family"
    # Carriers asked the audience question per request; below two, one at a time.
    audience_batch: int = 0
    # A frame's scene print: a newcomer that repeats a scene the cut holds is refused, as the
    # final duplicate review would take it out later with nothing in its place.
    scene_print: ScenePrint | None = None
    prepare_candidates: Callable[[Sequence[Mapping[str, Any]]], None] | None = None
    excluded: Mapping[str, str] = field(default_factory=dict)
    close_family_of: Callable[[str], Collection[str]] = lambda _asset: ()
    # Each moment's starred pictures: the one rule every pass that proposes a picture obeys.
    moment_favourites: Mapping[str, frozenset[str]] = field(default_factory=dict)
    decisions: list[dict[str, str]] = field(default_factory=list)

    def admit(
        self,
        carriers: Sequence[dict[str, Any]],
        *,
        tier_of: Mapping[str, str],
        protected: Sequence[str] = (),
    ) -> tuple[list[dict[str, Any]], list[GateRefusal]]:
        """The shots the gates keep, and the ones they refuse with the gate that refused them."""
        shots = sorted(carriers, key=itemgetter("taken", "asset_id"))
        self.settle(shots, tier_of)
        self.prefetch_audience([shot for shot in shots if self.stands_alone(shot, tier_of)])
        kept: list[dict[str, Any]] = []
        refused: list[GateRefusal] = []
        # Accepted depth supplements a representative, even when captured earlier.
        # Seat representatives first so depth cannot consume their spacing slot.
        # A moment's favourite is seated before its neighbours, which may only join it.
        for shot in sorted(
            shots, key=lambda row: (bool(row.get("depth")), not row.get("favourite"))
        ):
            refusal = self._refusal(shot, kept, tier_of)
            if refusal is None:
                kept.append(shot)
            else:
                refused.append(refusal)
        kept.sort(key=itemgetter("taken", "asset_id"))
        survivors, record = review_cut_by_cached_hashes(
            kept,
            thumbnail_hash=self.thumbnail_hash or (lambda _asset: None),
            protected_asset_ids=protected,
        )
        keeper_of = {row["asset_id"]: row["keeper"] for row in record["removals"]}
        refused.extend(
            _repeat_refusal(shot, keeper_of[shot["asset_id"]])
            for shot in kept
            if shot["asset_id"] in keeper_of
        )
        return survivors, refused

    def admits(
        self,
        candidate: Mapping[str, Any],
        *,
        cut: Sequence[Mapping[str, Any]],
        tier_of: Mapping[str, str],
        recovering: bool = False,
    ) -> GateRefusal | None:
        """Check and record one candidate against the cut it would join; None means admitted."""
        refusal = self._check(candidate, cut, tier_of, recovering=recovering)
        self.decisions.append(
            {
                "asset_id": candidate["asset_id"],
                "story": str(candidate.get("story_episode") or ""),
                "rule": refusal.rule if refusal else "admitted",
                "detail": refusal.detail if refusal else "passed candidate admission",
            }
        )
        return refusal

    def _check(self, candidate, cut, tier_of, *, recovering):
        if self.prepare_candidates is not None:
            self.prepare_candidates([candidate])
        self.settle([candidate], tier_of)
        refusal = self._refusal(candidate, list(cut), tier_of, recovering=recovering)
        if refusal is not None:
            return refusal
        if self.thumbnail_hash is None:
            return None
        # Protect the actual company: replacing a shot never displaces a second shot.
        company: list[dict[str, Any]] = [dict(row) for row in cut]
        survivors, record = review_cut_by_cached_hashes(
            [*company, dict(candidate)],
            thumbnail_hash=self.thumbnail_hash,
            protected_asset_ids=[row["asset_id"] for row in cut],
            scene_print=self.scene_print,
            close_family_of=self.close_family_of,
            # a newcomer's seconds are always spendable elsewhere: a repeat of it leaves
            content_floor=0.0,
        )
        if candidate["asset_id"] in {row["asset_id"] for row in survivors}:
            return None
        keeper = next(
            row["keeper"] for row in record["removals"] if row["asset_id"] == candidate["asset_id"]
        )
        return _repeat_refusal(candidate, keeper)

    def settle(self, shots: Sequence[Mapping[str, Any]], tier_of: Mapping[str, str]) -> None:
        """Put these shots to the standing gate together, asking only what can change an outcome.

        A starred shot the catalogue records is not refused on standing at all, so nothing is
        asked about it; the gate says what each other shot's standing turns on.
        """
        needs = {}
        for shot in shots:
            if self._source_refusal(shot) is not None:
                continue
            story = str(shot.get("story_episode") or "")
            needs[shot["asset_id"]] = (
                0
                if _owner_and_record(shot)
                else self.standing.needs(shot["asset_id"], _weight(shot, tier_of), story)
            )
        self.standing.ensure(list(needs), needs)

    def prefetch_audience(self, shots: Sequence[Mapping[str, Any]]) -> None:
        """Put these shots to the audience gate together, when it is asked in batches."""
        if self.audience is not None and self.audience_batch > 1 and shots:
            self.audience.prefetch(shots, batch=self.audience_batch)

    def stands_alone(self, shot: Mapping[str, Any], tier_of: Mapping[str, str]) -> bool:
        """The standing gate's answer for this shot as its story's weight reads it."""
        if self._source_refusal(shot) is not None:
            return False
        story = str(shot.get("story_episode") or "")
        stands = self.standing.stands(shot["asset_id"], _weight(shot, tier_of), story)
        return stands or _owner_and_record(shot)

    def _refusal(self, shot, kept, tier_of, *, recovering=False) -> GateRefusal | None:
        story = str(shot.get("story_episode") or "")
        moment = str(shot.get("moment") or "")
        asset = shot["asset_id"]
        source_refusal = self._source_refusal(shot)
        if source_refusal is not None:
            return source_refusal
        if not stands_for_its_moment(shot, kept, self.moment_favourites):
            return GateRefusal(asset, story, "favourite", "its moment's favourite is out", moment)
        stands = (
            (
                not self.standing.rejected_motion(asset)
                and self.standing.has_required_context(asset, _weight(shot, tier_of), story)
            )
            if recovering
            else self.stands_alone(shot, tier_of)
        )
        if not stands:
            weight = _weight(shot, tier_of)
            return GateRefusal(
                shot["asset_id"], story, "standing", f"as a {weight} story's shot", moment
            )
        verdict = self.audience.verdict_of(shot) if self.audience is not None else "share"
        if not allowed(verdict, self.audience_name):
            return GateRefusal(shot["asset_id"], story, "audience", verdict, moment)
        # Depth has already proved a new view inside a shown moment. Replacements
        # never inherit this exception from the picture whose slot they take.
        if not shot.get("depth") and not capture_space_available(shot, kept):
            return GateRefusal(
                shot["asset_id"], story, "capture spacing", "inside five minutes", moment
            )
        return None

    def _source_refusal(self, shot: Mapping[str, Any]) -> GateRefusal | None:
        for member in unit_members(shot):
            if member in self.excluded:
                return GateRefusal(
                    shot["asset_id"],
                    str(shot.get("story_episode") or ""),
                    "source",
                    self.excluded[member],
                    str(shot.get("moment") or ""),
                )
        return None


def _weight(shot: Mapping[str, Any], tier_of: Mapping[str, str]) -> str:
    return shot.get("story_weight") or WEIGHT_OF_TIER.get(
        tier_of.get(str(shot.get("story_episode") or ""), "background"), "glimpse"
    )


def _repeat_refusal(shot: Mapping[str, Any], keeper: str) -> GateRefusal:
    return GateRefusal(
        asset_id=shot["asset_id"],
        story=str(shot.get("story_episode") or ""),
        rule="look-alike",
        detail=f"repeats {keeper[:8]} by cached preview hash",
        moment=str(shot.get("moment") or ""),
    )


def _owner_and_record(shot: Mapping[str, Any]) -> bool:
    """The favourite wins its moment: a picture the owner starred that the catalogue also
    records something about is not refused on a standing answer read off its text alone.
    The audience gate still decides."""
    return bool(shot.get("favourite") and shot.get("notable_record"))


def shows_life(material: Material, unit_of, asset_id: str) -> bool:
    """Whether this picture's unit reads as people or life, not a lone object."""
    u = unit_of.get(asset_id)
    return bool(u) and material.text.shows_life(u) and not material.text.lone_object(u)


def picture_admission(source, ports, material, selection, gate) -> PictureAdmission:
    """Use the same fresh facts for every picture proposed after story allocation."""
    unit_by_asset = {u["asset_id"]: (f, u) for f, units in material.units.items() for u in units}
    unit_of = {asset: unit for asset, (_family, unit) in unit_by_asset.items()}
    standing = StandingGate(
        (ports.rules or RuleStructureReader(source)).standing,
        line_of=lambda asset_id: selection.lines.get(asset_id, ""),
        life=lambda asset_id: shows_life(material, unit_of, asset_id),
        unit_by_asset=unit_by_asset,
        pictures_of={s["key"]: s["seen"]["pictures"] for s in selection.story.stories},
        context_without_life=source.intent.context_without_life,
        pool_is_subject=source.intent.pool_is_subject,
    )

    def prepare_candidates(rows):
        gate.prepare(rows)
        standing.refresh([row["asset_id"] for row in rows])

    close_of = film_close_family(source)

    return PictureAdmission(
        standing=standing,
        audience=gate,
        thumbnail_hash=ports.thumbnail_hash,
        scene_print=ports.scene_print,
        audience_name=source.audience,
        audience_batch=16 if ports.laya else 0,
        prepare_candidates=prepare_candidates,
        excluded=material.document_sources,
        close_family_of=lambda asset: close_of(selection.lines.get(asset, "")),
        moment_favourites=favourites_by_moment(unit_of.values()),
    )
