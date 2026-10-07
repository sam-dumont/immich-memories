"""Closeness weighting for birthdays, spotlights, pairs and groups (#2232)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from immich_memories.automation.calendar_detectors import BirthdayDetector, PersonSpotlightDetector
from immich_memories.automation.closeness import closeness_weight, group_weight
from immich_memories.automation.event_detectors import MultiPersonDetector


def _context(tier: str | None = None, role: str | None = None):
    return SimpleNamespace(tier=tier, role=role)


def _person(pid: str, name: str, birth: date | None = None):
    return SimpleNamespace(id=pid, name=name, thumbnail_path="/t.jpg", birth_date=birth)


def test_weights_follow_the_tier_and_a_close_family_role_is_always_full():
    assert closeness_weight(_context(tier="inner")) == 1.0
    assert closeness_weight(_context(tier="recurring")) == 0.6
    assert closeness_weight(_context(tier="episodic")) == 0.3
    assert closeness_weight(_context(tier="event")) == 0.15
    assert closeness_weight(_context(tier="episodic", role="son")) == 1.0
    assert closeness_weight(_context()) is None


def test_a_pair_weighs_the_average_of_its_people_and_unknown_is_not_marked_down():
    assert group_weight(["a", "b"], {"a": 1.0, "b": 0.3}) == 0.65
    assert group_weight(["a", "b"], None) == 1.0
    assert group_weight(["a", "stranger"], {"a": 0.6}) == 0.8


TODAY = date(2026, 3, 20)
BIRTHDAY = date(2015, 3, 10)


def _birthday(closeness, counts, max_count=None, days=None, notes=None):
    people = [_person("p1", "Kid", BIRTHDAY)]
    return BirthdayDetector().detect(
        {},
        people,
        set(),
        None,
        TODAY,
        person_asset_counts=counts,
        closeness=closeness,
        busiest_count=max_count,
        distinct_days=days,
        notes=notes,
    )


def test_a_birthday_is_scaled_by_closeness_and_by_pictures_against_the_busiest_person():
    inner = _birthday({"p1": 1.0}, {"p1": 400}, max_count=400)[0]
    acquaintance = _birthday({"p1": 0.3}, {"p1": 400}, max_count=400)[0]
    thin = _birthday({"p1": 1.0}, {"p1": 100}, max_count=400)[0]

    assert inner.score == 0.75
    assert acquaintance.score == round(0.75 * 0.3, 3)
    # 100 of 400 would be 0.25 of the busiest; the floor is 0.5.
    assert thin.score == round(0.75 * 0.5, 3)


def test_no_birthday_film_under_fifty_pictures_and_the_reason_is_given():
    notes: list[str] = []

    result = _birthday({"p1": 0.3}, {"p1": 36}, max_count=400, notes=notes)

    assert result == []
    assert "36 pictures" in notes[0] and "50" in notes[0]


def test_no_birthday_film_under_three_distinct_days():
    notes: list[str] = []

    result = _birthday({"p1": 1.0}, {"p1": 80}, max_count=400, days={"p1": 2}, notes=notes)

    assert result == []
    assert "2 days" in notes[0]


def test_without_closeness_a_birthday_keeps_its_old_score():
    (candidate,) = _birthday(None, None)

    assert candidate.score == 0.75


def test_a_spotlight_is_scaled_by_closeness():
    people = [_person("p1", "Kid"), _person("p2", "Cousin")]
    counts = {"p1": 400, "p2": 400}

    found = {
        c.person_names[0]: c.score
        for c in PersonSpotlightDetector().detect(
            {},
            people,
            set(),
            None,
            date(2026, 3, 20),
            person_asset_counts=counts,
            closeness={"p1": 1.0, "p2": 0.3},
        )
    }

    assert found["Cousin"] == round(found["Kid"] * 0.3, 3)


def test_a_pair_is_scaled_by_the_average_closeness_of_its_two_people():
    people = [_person("p1", "Kid"), _person("p2", "Cousin")]

    def score(closeness):
        (candidate,) = MultiPersonDetector().detect(
            {},
            people,
            set(),
            None,
            date(2026, 3, 20),
            person_asset_counts={"p1": 900, "p2": 900},
            shared_counts={("p1", "p2"): 500},
            closeness=closeness,
        )
        return candidate.score

    assert score({"p1": 1.0, "p2": 0.3}) == round(score(None) * 0.65, 3)
