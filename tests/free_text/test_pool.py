"""The pool: the pictures a request can be filmed from, filter by filter, with a verdict."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from immich_memories.free_text.facts import LibraryFacts
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household, WhenLink, WhereLink, WhoLink
from immich_memories.free_text.pool import Translation, build_pool
from immich_memories.free_text.reading import Reading
from immich_memories.free_text.subject import Subject
from tests.free_text.banked import BankedAsker

NOBODY = Household({})


def _picture(asset_id: str, day: str = "2020-05-01", **fields: Any) -> LibraryPicture:
    taken_at = datetime.fromisoformat(day).replace(hour=12, tzinfo=UTC)
    fields.setdefault("media_kind", "photo")
    return LibraryPicture(asset_id=asset_id, taken_at=taken_at, **fields)


def _view(*pictures: LibraryPicture, **fields: Any) -> LibraryView:
    fields.setdefault("people", {})
    fields.setdefault("sharpness_line", None)
    return LibraryView(pictures=tuple(sorted(pictures, key=lambda p: p.taken_at)), **fields)


def _asked(request: str, *, main: tuple[str, ...] = (), **parts: Any) -> Translation:
    return Translation(
        reading=parts.pop("reading", Reading(request=request)),
        who=parts.pop("who", WhoLink()),
        when=parts.pop("when", WhenLink()),
        where=parts.pop("where", WhereLink()),
        facts=parts.pop("facts", LibraryFacts()),
        subject=parts.pop("subject", Subject(heads=main, words=main, main=main)),
    )


def _cats(count: int, start: str = "2020-01-01") -> list[LibraryPicture]:
    first = date.fromisoformat(start)
    return [
        _picture(f"cat-{n}", str(first + timedelta(days=n)), caption="A black cat is sleeping")
        for n in range(count)
    ]


def _ids(pool: Any) -> set[str]:
    return {picture.asset_id for picture in pool.pictures}


def test_the_pool_is_the_dated_pictures_whose_caption_is_about_the_subject(
    lexicon: Lexicon,
) -> None:
    view = _view(
        *_cats(14),
        _picture("held", "2020-01-03", caption="A man holding a cat in a garden"),
        _picture("before", "2019-06-01", caption="A cat on a windowsill"),
    )
    asked = _asked(
        "our cat since 2020",
        main=("cat",),
        when=WhenLink(start=date(2020, 1, 1)),
    )

    pool = build_pool(asked, view, NOBODY, lexicon, BankedAsker())

    assert _ids(pool) == {f"cat-{n}" for n in range(14)}
    assert [(step.name, step.kept) for step in pool.funnel] == [
        ("library", 16),
        ("when", 15),
        ("subject", 14),
    ]
    assert pool.verdict == "possible"


def test_a_few_pictures_are_thin_and_none_is_not_possible_with_the_step_that_emptied_it(
    lexicon: Lexicon,
) -> None:
    few = build_pool(
        _asked("our cat", main=("cat",)), _view(*_cats(3)), NOBODY, lexicon, BankedAsker()
    )
    none = build_pool(
        _asked("brunches", main=("brunch",)), _view(*_cats(3)), NOBODY, lexicon, BankedAsker()
    )

    assert few.verdict == "thin"
    assert "3 pictures" in few.why
    assert none.verdict == "not possible"
    assert "subject" in none.why
    assert "brunch" in none.why
