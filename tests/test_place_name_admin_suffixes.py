"""Estonian administrative wording never reaches a label.

#1971 taught the stripper in `place_names.py` to drop Greek administrative wording; #2066
(found in the #1719 campaign) found the same boilerplate problem for Estonian's admin
words, which sit after the place name rather than before it.
"""

from __future__ import annotations

import pytest

from immich_memories.place_names import degraded_locality_name, locality_name

# Through the public label seam: a viewer must never read the admin word, whatever form
# Nominatim answered with, and a name that only looks like a suffix must survive intact.
_CASES = [
    # Estonian, nominative: the admin word is a separate trailing word.
    ("Saku vald", "Saku"),
    ("Pärnu linn", "Pärnu"),
    ("Aegviidu alev", "Aegviidu"),
    ("Puhja alevik", "Puhja"),
    ("Rapla maakond", "Rapla"),
    ("Vändra küla", "Vändra"),
    # Estonian, genitive admin word (#2066): Nominatim sometimes answers this way; the
    # bare name must come out the same as the nominative form above.
    ("Saku valla", "Saku"),
    ("Pärnu linna", "Pärnu"),
    # A hyphenated real name still loses only the trailing admin word.
    ("Narva-Jõesuu linn", "Narva-Jõesuu"),
    # A name that only *looks* like it carries a suffix must stay whole: there is no
    # space before "linn"/"linna" inside these real names, so nothing is stripped.
    ("Tallinn", "Tallinn"),
    ("Tallinna", "Tallinna"),
    # The admin word on its own, with nothing in front of it to strip, is still a name.
    ("Linna", "Linna"),
    ("Vald", "Vald"),
]


@pytest.mark.parametrize(("label", "expected"), _CASES)
def test_administrative_wording_never_reaches_the_label(label: str, expected: str) -> None:
    assert locality_name(label) == expected


# #2074: Latvian (novads, pagasts), Lithuanian (savivaldybė, seniūnija) and Finnish (kunta,
# kaupunki) admin words sit in the same Nominatim table as Estonian's, but the name in
# front of them is genitive, not nominative ("Helsingin" is "of Helsinki", not "Helsinki").
# Unlike Estonian, these are never stripped to a bare (declined) name: the label names
# nothing at this scale, the same treatment #1971 gave the Greek inflected prefixes, so a
# caller falls back to Immich's own `exif.city` (always GeoNames' nominative name).
_GENITIVE_SUFFIX_CASES = [
    "Helsingin kaupunki",
    "Espoon kaupunki",
    "Nurmijärven kunta",
    "Cēsu novads",
    "Mārupes novads",
    "Ikšķiles pagasts",
    "Vilniaus savivaldybė",
    "Kauno seniūnija",
]


@pytest.mark.parametrize("label", _GENITIVE_SUFFIX_CASES)
def test_genitive_admin_suffixes_name_nothing_at_this_scale(label: str) -> None:
    assert locality_name(label) is None


@pytest.mark.parametrize(
    ("label", "expected"),
    [(label, label.rsplit(" ", 1)[0]) for label in _GENITIVE_SUFFIX_CASES],
)
def test_genitive_admin_suffixes_degrade_to_the_declined_stem(label: str, expected: str) -> None:
    assert degraded_locality_name(label) == expected
