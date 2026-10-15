"""A store id `people show` lists picks its one person, whatever shape the id has."""

from __future__ import annotations

import pytest

from immich_memories.analysis.sources.person_resolution import (
    PersonAlias,
    StorePerson,
    resolve_people,
)
from immich_memories.api.person_expression import PersonExpression

_KIT = StorePerson("kit-face", "Kit", (PersonAlias("kit-face", "primary"),))
# Another person the registry also calls Kit: asking by the name asks for both.
_OTHER_KIT = StorePerson("other-face", "Kit", (PersonAlias("other-face", "primary"),))
_JO = StorePerson("jo-face", "Jo", (PersonAlias("jo-face", "primary"),))
_STORE = (_KIT, _OTHER_KIT, _JO)


def _never_the_roster(name: str) -> PersonExpression:
    raise AssertionError(f"{name!r} went to the Immich roster")


def _faces(leaf: str) -> set[str]:
    resolved = resolve_people(PersonExpression("person", value=leaf), _STORE, _never_the_roster)
    return set(resolved.condition.leaf_values)


def test_a_store_id_that_is_not_a_uuid_picks_exactly_that_person():
    assert _faces("other-face") == {"other-face"}


def test_a_shared_name_still_picks_everyone_carrying_it():
    assert _faces("Kit") == {"kit-face", "other-face"}


def test_a_leaf_neither_a_name_nor_a_store_id_goes_to_the_roster():
    with pytest.raises(AssertionError, match="went to the Immich roster"):
        _faces("nobody-here")
