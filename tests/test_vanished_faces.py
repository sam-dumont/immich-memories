"""A store face Immich no longer has is followed by name, once and only when unambiguous."""

from __future__ import annotations

from immich_memories.analysis.sources.person_resolution import (
    PersonAlias,
    StorePerson,
    follow_vanished_faces,
)
from immich_memories.automation.people_merge import canonical_person_map


def _person(person_id: str, name: str, *faces: str, account: str = "primary") -> StorePerson:
    return StorePerson(person_id, name, tuple(PersonAlias(face, account) for face in faces))


def test_a_vanished_face_follows_the_one_roster_person_with_that_name():
    kit = _person("kit-old", "Kit", "kit-old")

    followed = follow_vanished_faces((kit,), {"kit-new": "kit"})

    assert followed.people == (_person("kit-old", "Kit", "kit-new"),)
    assert followed.followed == ((followed.people[0], "kit-new"),)
    assert followed.lost == ()
    # Discovery folds the live face into the person the store's answers are about.
    assert canonical_person_map(followed.people) == {("primary", "kit-new"): "kit-old"}


def test_two_roster_people_with_the_name_follow_neither():
    kit = _person("kit-old", "Kit", "kit-old")

    followed = follow_vanished_faces((kit,), {"a": "Kit", "b": "Kit"})

    assert followed.lost == (kit,)
    assert followed.people == (_person("kit-old", "Kit"),)


def test_a_record_of_the_same_name_holding_the_face_answers_for_both():
    # The face the name leads to is already the store's second record of the same human:
    # that record answers until the next scan folds the two together.
    kit = _person("kit-old", "Kit", "kit-old")
    other = _person("kit-new", "Kit", "kit-new")

    followed = follow_vanished_faces((kit, other), {"kit-new": "Kit"})

    assert followed.people == (_person("kit-old", "Kit"), other)
    assert followed.followed == () and followed.lost == ()


def test_a_face_a_differently_named_person_holds_is_never_taken():
    kit = _person("kit-old", "Kit", "kit-old")
    other = _person("jo", "Jo", "kit-new")

    followed = follow_vanished_faces((kit, other), {"kit-new": "Kit"})

    assert followed.lost == (kit,)


def test_a_person_with_a_live_face_only_drops_the_dead_one():
    jo = _person("jo-a", "Jo", "jo-a", "jo-gone")

    followed = follow_vanished_faces((jo,), {"jo-a": "Jo"})

    assert followed.people == (_person("jo-a", "Jo", "jo-a"),)
    assert followed.followed == () and followed.lost == ()


def test_another_accounts_faces_and_manual_people_are_left_alone():
    partner = _person("pat", "Pat", "pat-q", account="partner")
    manual = StorePerson("manual:1", "Nan", ())

    followed = follow_vanished_faces((partner, manual), {})

    assert followed.people == (partner, manual)
    assert followed.lost == ()
