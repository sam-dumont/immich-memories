"""An ordinary request (no negation, no "only") must give the same result as main (#2061
round 4). Round 3 replaced the required-company match with a curated word list and lost
real photos a WordNet match already recognised (skiers, a father and son embracing); the
whole-request negation fallback also turned an unrelated word ("band") into a required
company for a request that never asked for one. Both regressions are checked here against
the real pinned WordNet corpus, not the small per-test one, since the lost coverage was
WordNet's own breadth.
"""

from __future__ import annotations

import os
import pwd
from datetime import UTC, datetime
from pathlib import Path

import pytest

from immich_memories.free_text.facts import LibraryFacts
from immich_memories.free_text.lexicon import Lexicon, WordNetUnavailable, load_wordnet
from immich_memories.free_text.library import LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household, WhenLink, WhereLink, WhoLink, link_who
from immich_memories.free_text.pool import Translation, build_pool
from immich_memories.free_text.reading import Reading
from immich_memories.free_text.subject import Subject
from tests.free_text.banked import BankedAsker

NOBODY = Household({})


@pytest.fixture(scope="module")
def real_lexicon() -> Lexicon:
    # The real account's home, not the disposable one the unit suite seals HOME to: a
    # read-only pinned corpus, never a store, carries none of that seal's mutation risk.
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    path = real_home / ".immich-memories" / "models" / "wordnet" / "wordnet.zip"
    try:
        return load_wordnet(path)
    except WordNetUnavailable:
        pytest.skip("the real pinned WordNet corpus is not installed (`models fetch`)")


def _picture(asset_id: str, caption: str) -> LibraryPicture:
    return LibraryPicture(
        asset_id=asset_id,
        taken_at=datetime(2024, 1, 1, 12, tzinfo=UTC),
        media_kind="photo",
        caption=caption,
    )


def _asked(main: tuple[str, ...], who: WhoLink) -> Translation:
    return Translation(
        reading=Reading(request=""),
        who=who,
        when=WhenLink(),
        where=WhereLink(),
        facts=LibraryFacts(),
        subject=Subject(heads=main, words=main, main=main),
    )


def test_with_friends_keeps_what_wordnet_already_recognised_as_people(
    real_lexicon: Lexicon,
) -> None:
    view = LibraryView(
        pictures=(
            _picture("skier", "A skier going down a snowy mountain slope"),
            _picture("snowboarder", "A snowboarder jumping over a ramp"),
            _picture("group", "A group of friends laughing by a campfire"),
            _picture("empty", "An empty mountain cabin at dusk"),
        ),
        people={},
        sharpness_line=None,
    )
    who = link_who(
        "weekend in the mountains with friends", ("friends",), NOBODY, real_lexicon, BankedAsker()
    )
    asked = _asked((), who)

    pool = build_pool(asked, view, NOBODY, real_lexicon, BankedAsker())

    assert {p.asset_id for p in pool.pictures} == {"skier", "snowboarder", "group"}


def test_with_the_kids_keeps_a_father_and_son_embracing(real_lexicon: Lexicon) -> None:
    view = LibraryView(
        pictures=(
            _picture("embrace", "A father and son embracing on the beach"),
            _picture("sandcastle", "A child building a sandcastle"),
            _picture("empty", "An empty beach at sunset"),
        ),
        people={},
        sharpness_line=None,
    )
    who = link_who("beach days with the kids", ("kids",), NOBODY, real_lexicon, BankedAsker())
    asked = _asked((), who)

    pool = build_pool(asked, view, NOBODY, real_lexicon, BankedAsker())

    assert {p.asset_id for p in pool.pictures} == {"embrace", "sandcastle"}


def test_my_sons_band_concerts_sets_no_required_company_from_the_whole_text(
    real_lexicon: Lexicon,
) -> None:
    # #2061 round 4: the reader can put nothing useful in `who`; the whole-request
    # negation/only fallback must not turn "band" into a required company on its own.
    who = link_who("my son's band concerts", (), NOBODY, real_lexicon, BankedAsker())

    assert who.company is None
    assert who.absent_company is None


def test_christmas_with_the_family_is_not_narrowed_by_the_whole_text_fallback(
    real_lexicon: Lexicon,
) -> None:
    view = LibraryView(
        pictures=(
            _picture("tree", "A family gathered around a Christmas tree"),
            _picture("dinner", "A family eating dinner at a decorated table"),
            _picture("empty", "A decorated Christmas tree with no one in the room"),
        ),
        people={},
        sharpness_line=None,
    )
    who = link_who("Christmas with the family", ("family",), NOBODY, real_lexicon, BankedAsker())
    asked = _asked((), who)

    pool = build_pool(asked, view, NOBODY, real_lexicon, BankedAsker())

    assert {p.asset_id for p in pool.pictures} == {"tree", "dinner"}


def test_a_subject_only_request_sets_no_company_at_all(real_lexicon: Lexicon) -> None:
    dog = link_who("the dog", (), NOBODY, real_lexicon, BankedAsker())
    trip = link_who("our trip to italy", (), NOBODY, real_lexicon, BankedAsker())

    assert (dog.company, dog.absent_company) == (None, None)
    assert (trip.company, trip.absent_company) == (None, None)
