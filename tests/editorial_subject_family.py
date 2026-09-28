"""A synthetic people registry for a film about the owner's partner, whose parents are hers alone.

The owner calls them in-laws, so to the owner they are nobody close; to the film's subject they
are her father and mother. Roles only.
"""

from __future__ import annotations

from types import SimpleNamespace

from immich_memories.analysis.editorial_people import EditorialPeople, adapt_editorial_people
from immich_memories.people.context import load_people_prompt_context
from tests.people_registry_seed import seed_people

PEOPLE_FILE = """
version: 1
owner: {person_id: owner-id, identified: confirmed}
people:
  - {ids: [owner-id], name: Owner}
  - name: Subject
    ids: [subject-id]
    confirmed:
      role: partner
      links:
        - {kind: partner-of, with: owner-id}
        - {kind: child-of, with: her-father-id}
  - {ids: [her-father-id], name: Her Father}
  - name: Her Mother
    ids: [her-mother-id]
    confirmed: {links: [{kind: mother-of, with: subject-id}]}
"""


def subject_people() -> tuple[EditorialPeople, dict[str, str]]:
    """The people registry's facts, and each person's relation to the owner as a line renders it."""
    context = load_people_prompt_context(seed_people(PEOPLE_FILE), include_derived=True)
    return adapt_editorial_people(context), {c.name: c.relationship for c in context.values()}


def her_parents(relation: dict[str, str]) -> str:
    """The `with` clause of a picture of the subject's father and mother."""
    return "with " + "; ".join(
        f"{name} ({relation[name]})" for name in ("Her Father", "Her Mother")
    )


def film_of(product: str) -> SimpleNamespace:
    """The parts of a planning source that say whose film it is."""
    people, _relation = subject_people()
    return SimpleNamespace(
        case=SimpleNamespace(product=product, people=("Subject",)), people=people
    )
