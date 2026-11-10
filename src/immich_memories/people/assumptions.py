"""Reviewable family consequences of facts the user already confirmed.

This is deliberately normative graph closure, not truth. The editor's suggestion engine
(`people.kinship`) does the deriving, so the prompts read the same chained family the
People page offers: siblings share parents, a sibling's sibling is a sibling, and the
grandparents, cousins, aunts, uncles and in-laws follow those chains. A declined answer
is never proposed or built on. The output is always labelled as derived context and
never written to ``confirmed:``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from immich_memories.people.companion import people_entries
from immich_memories.people.kinship import (
    Hop,
    Suggestion,
    facts_from_document,
    suggest_relationships,
)

# The side of a pair a proposal is told from: the elder generation, else the lower id.
_ELDER_KINDS = frozenset({"parent-of", "grandparent-of", "aunt-or-uncle-of", "parent-in-law-of"})


@dataclass(frozen=True)
class ConfirmedStep:
    """One normalized confirmed edge that supports an assumption."""

    source_id: str
    kind: str
    target_id: str


@dataclass(frozen=True)
class RelationshipAssumption:
    """One proposal for review, with no invented probability."""

    source_id: str
    kind: str
    target_id: str
    reverse_kind: str
    evidence: tuple[ConfirmedStep, ...]


def family_assumptions(document: dict[str, Any]) -> tuple[RelationshipAssumption, ...]:
    """Derive conventional kinship proposals from confirmed facts only, one per pair."""
    facts, declined = facts_from_document(people_entries(document))
    confirmed_pairs = {frozenset((fact.source, fact.target)) for fact in facts}
    readings: dict[frozenset[str], dict[tuple[str, str], RelationshipAssumption]] = defaultdict(
        dict
    )
    for suggestion in suggest_relationships(facts, declined):
        pair = frozenset((suggestion.source, suggestion.target))
        if pair in confirmed_pairs or not _told_from_this_side(suggestion):
            continue
        readings[pair].setdefault(
            (suggestion.kind, suggestion.reverse_kind),
            RelationshipAssumption(
                suggestion.source,
                suggestion.kind,
                suggestion.target,
                suggestion.reverse_kind,
                _steps(suggestion.source, suggestion.hops),
            ),
        )

    # A pair that can be read two different ways is not a review candidate; it
    # is evidence that the normative closure does not fit this family.
    unambiguous = [next(iter(found.values())) for found in readings.values() if len(found) == 1]
    return tuple(sorted(unambiguous, key=_assumption_key))


def _told_from_this_side(suggestion: Suggestion) -> bool:
    """The engine offers both sides of a pair; the prompt reads one and adds the reverse."""
    if suggestion.reverse_kind in _ELDER_KINDS:
        return False
    return suggestion.kind in _ELDER_KINDS or suggestion.source < suggestion.target


def _steps(start: str, hops: tuple[Hop, ...]) -> tuple[ConfirmedStep, ...]:
    """The chain as recorded edges, a child's parent written as the parent's own."""
    steps = []
    here = start
    for hop in hops:
        if hop.relation == "child":
            steps.append(ConfirmedStep(hop.person, "parent-of", here))
        else:
            steps.append(ConfirmedStep(here, f"{hop.relation}-of", hop.person))
        here = hop.person
    return tuple(steps)


def _assumption_key(assumption: RelationshipAssumption) -> tuple[str, str, str]:
    return assumption.kind, assumption.source_id, assumption.target_id
