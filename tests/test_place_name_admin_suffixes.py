"""Estonian, Latvian, Lithuanian and Finnish administrative wording never reaches a label.

#1971 taught the stripper in `place_names.py` to drop Greek administrative wording; #2066
(found in the #1719 campaign) found the same boilerplate problem for the Baltic and Nordic
admin words, which sit after the place name rather than before it.
"""

from __future__ import annotations

import pytest

from immich_memories.place_names import locality_name

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
    # Latvian, Lithuanian, Finnish: the same "name + admin word" shape.
    ("Cēsu novads", "Cēsu"),
    ("Mārupes pagasts", "Mārupes"),
    ("Vilniaus savivaldybė", "Vilniaus"),
    ("Žirmūnų seniūnija", "Žirmūnų"),
    ("Espoon kunta", "Espoon"),
    ("Helsingin kaupunki", "Helsingin"),
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
