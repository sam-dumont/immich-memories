"""The rule preview: which of the editor's rules would drop pool pictures, before render.

The pool funnel says which pictures mean the request. The editor then refuses some of them on
rules that protect every film: a screenshot, a copy of a picture it already has, a picture held
for review. This asks those rules about the pool before anything renders, through the functions
the run itself calls on the same banked facts, so the preview and the run cannot disagree. A rule
that depends on the shots around a picture, or on a model reading, is only known while cutting:
it is named, never counted.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from immich_memories.analysis.editorial_carrier_eligibility import excluded_carrier_sources
from immich_memories.analysis.editorial_clip_frames import unusable_video
from immich_memories.analysis.editorial_shareability import (
    load_flags,
    never_auto_ids,
    partition_units,
    unit_members,
)
from immich_memories.analysis.editorial_source_gate import screen_document_rejections
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    PreparedEditorialSource,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.analysis.source_filter import asset_of
from immich_memories.tracking.report_privacy import ReportPrivacy

if TYPE_CHECKING:
    from immich_memories.analysis.editorial_runtime_evidence import AnnotationReadings
    from immich_memories.api.models import Asset, VideoClipInfo

# How many pictures a rule shows as its examples.
EXAMPLES = 3

# A source refusal's reason, as the source pass words it, and the rule it belongs to.
_SOURCE_RULES = (
    ("another file of the same picture", "another file of the same picture"),
    ("not on the timeline", "hidden in Immich"),
    ("a film this app generated", "a film this app made"),
    ("source video runs", "long video"),
    ("video duration metadata is missing", "long video"),
)
# Carrier refusals that are not screens (those are the source gate's, which answers first).
_CARRIER_RULES = {
    "face-close-up": "close-up of a face part",
    "medical-care": "medical care",
    "identical-grid": "sheet of identical portraits",
}
_WHY = {
    "another file of the same picture": "the full-size file of the same picture plays instead",
    "hidden in Immich": "archived, hidden or locked: not on the timeline",
    "a film this app made": "a finished memory is not footage of anything",
    "long video": "a recording over the source cap is never downloaded",
    "screens and documents": "a screenshot, a screen or a document is never a source",
    "held for review": "a detector or you marked it never_auto; only your clearance lifts it",
    "close-up of a face part": "a close-up of an eye or a mouth needs an explanation",
    "medical care": "an ailment or a care item on a person stays out",
    "sheet of identical portraits": "a sheet of ID photos is an identification document",
    "video frames miss the subject": "its sampled frames often miss the subject; a starred "
    "video stays",
}
SCREENS, HELD, FRAMES = "screens and documents", "held for review", "video frames miss the subject"


@dataclass(frozen=True)
class RuleDrop:
    """One rule, the pool pictures it would drop, and why it drops them."""

    rule: str
    why: str
    asset_ids: tuple[str, ...]

    @property
    def examples(self) -> tuple[str, ...]:
        """The first few of its pictures, in the pool's order."""
        return self.asset_ids[:EXAMPLES]


@dataclass(frozen=True)
class RuleNote:
    """A rule the preview names without a count: decided while cutting, or not applied."""

    rule: str
    why: str


@dataclass(frozen=True)
class RulePreview:
    """What the editor's rules would do to the pool, before render."""

    checked: int
    drops: tuple[RuleDrop, ...]
    # Pictures preparation has not read yet: the run reads them first, then these rules apply.
    unread: int
    at_cut: tuple[RuleNote, ...]
    lifted: tuple[RuleNote, ...]
    # Each example's hashed id, the way a report hashes it: the terminal never prints an id.
    hashed: Mapping[str, str]

    @property
    def passed(self) -> int:
        """The pool pictures no rule the preview can check would drop."""
        return self.checked - sum(len(drop.asset_ids) for drop in self.drops)

    def lines(self) -> list[str]:
        """The RULES block of the trace: a count per rule, a few hashed ids, then the notes."""
        said = [f"{self.passed} of {self.checked} pictures pass the rules checked before cutting"]
        said += [
            f"{drop.rule}: {len(drop.asset_ids)} ({drop.why}) "
            + ", ".join(self.hashed[asset_id] for asset_id in drop.examples)
            for drop in self.drops
        ]
        if self.unread:
            said.append(
                f"not prepared yet: {self.unread} pictures; the run reads them first, "
                "then these rules apply"
            )
        return [
            *said,
            "decided while cutting: " + _notes(self.at_cut),
            "not applied to a film you asked for: " + _notes(self.lifted),
        ]

    def record(self) -> dict[str, object]:
        """The preview as data for a watcher: raw example ids, for its thumbnails."""
        return {
            "checked": self.checked,
            "passed": self.passed,
            "unread": self.unread,
            "drops": [
                {
                    "rule": drop.rule,
                    "why": drop.why,
                    "count": len(drop.asset_ids),
                    "examples": list(drop.examples),
                }
                for drop in self.drops
            ],
            "at_cut": [{"rule": note.rule, "why": note.why} for note in self.at_cut],
            "lifted": [{"rule": note.rule, "why": note.why} for note in self.lifted],
        }


def preview_rules(
    sources: Sequence[Asset | VideoClipInfo],
    *,
    scope: SourceScope,
    readings: AnnotationReadings,
    audience: str,
    preview_jpeg: Callable[[Asset], bytes | None] | None = None,
) -> RulePreview:
    """Ask the editor's rules about the pool's `sources`, as the run would before cutting.

    `scope` is the run's source scope and `readings` its line reader; `preview_jpeg` reads the
    cached previews the run's copy check reads. Each picture counts under the first rule that
    drops it, in the run's order: source, screens, holds, carrier rules, then video frames.
    """
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=scope),
        EditorialDependencies(source_fetcher=lambda _scope: sources, preview_jpeg=preview_jpeg),
        group=False,
    )
    order = tuple(dict.fromkeys(asset_of(source).id for source in sources))
    fates = _source_fates(prepared)
    readable = tuple(prepared.candidate_ids)
    unread = 0
    if readable:
        batch = readings.reader(prepared).lines_for(readable)
        lines = batch.as_mapping()
        unread = sum(not line.description and not line.heads for line in batch.lines)
        _first(fates, dict.fromkeys(screen_document_rejections(batch), SCREENS))
        _first(fates, dict.fromkeys(_held(prepared, readings), HELD))
        _first(fates, _carrier_fates(lines))
        _first(fates, dict.fromkeys(_frames_miss(prepared, lines), FRAMES))
    # In the run's order of rules; each rule's pictures in the pool's order.
    drops = [
        RuleDrop(rule, _WHY.get(rule, rule), tuple(a for a in order if fates.get(a) == rule))
        for rule in dict.fromkeys(fates.values())
    ]
    privacy = ReportPrivacy()
    return RulePreview(
        checked=len(order),
        drops=tuple(drops),
        unread=unread,
        at_cut=_at_cut(audience),
        lifted=_lifted(scope),
        hashed={a: privacy.hash_id(a) for drop in drops for a in drop.examples},
    )


def _source_fates(prepared: PreparedEditorialSource) -> dict[str, str]:
    source_pass = next(
        trace for trace in prepared.trace.editorial_passes if trace.name == "source-eligibility"
    )
    fates = {}
    for decision in source_pass.rejected:
        rule = next(
            (rule for start, rule in _SOURCE_RULES if decision.reason.startswith(start)),
            decision.reason,
        )
        # A Live Photo's clip is part of its still, which carries it: no picture is lost.
        if decision.reason != "Live Photo component":
            fates[decision.asset_id] = rule
    return fates


def _held(prepared: PreparedEditorialSource, readings: AnnotationReadings) -> list[str]:
    # A Live Photo is held whole when its still or its clip is flagged, as the run holds it.
    units = [
        {"asset_id": c.asset_id, "video_ids": [c.source.live_photo_video_id or ""]}
        for c in prepared.candidates
    ]
    members = [member for unit in units for member in unit_members(unit)]
    held = never_auto_ids(load_flags(readings.store, members))
    _kept, excluded = partition_units(units, held)
    return [str(unit["asset_id"]) for unit in excluded]


def _carrier_fates(lines: Mapping[str, str]) -> dict[str, str]:
    return {
        asset_id: _CARRIER_RULES[reason]
        for asset_id, reason in excluded_carrier_sources(lines).items()
        if reason in _CARRIER_RULES
    }


def _frames_miss(prepared: PreparedEditorialSource, lines: Mapping[str, str]) -> list[str]:
    return [
        c.asset_id
        for c in prepared.candidates
        if unusable_video(
            {"kind": c.media_kind, "favourite": c.favourite}, lines.get(c.asset_id, "")
        )
    ]


def _notes(notes: Sequence[RuleNote]) -> str:
    return "; ".join(f"{note.rule} ({note.why})" for note in notes)


def _first(fates: dict[str, str], found: Mapping[str, str]) -> None:
    for asset_id, rule in found.items():
        fates.setdefault(asset_id, rule)


def _at_cut(audience: str) -> tuple[RuleNote, ...]:
    return (
        RuleNote(
            "who sees it",
            f"the model reads each chosen shot's caption for a {audience.replace('_', '-')} film; "
            "a detector hold keeps a picture out of shared films",
        ),
        RuleNote("look-alikes", "a shot that repeats one already in the cut, by its preview"),
        RuleNote("capture spacing", "two shots of one moment inside five minutes"),
    )


def _lifted(scope: SourceScope) -> tuple[RuleNote, ...]:
    standing = RuleNote(
        "standing", "a pool picture stands on the subject you asked for; its score is no veto"
    )
    if not scope.accept_any_provenance:
        return (standing,)
    provenance = RuleNote("provenance", "forwarded and saved pictures stay in a film you asked for")
    return (provenance, standing)
