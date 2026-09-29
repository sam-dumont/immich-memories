"""What the library measures, linked to a request's words by code."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from immich_memories.free_text.facts import link_facts
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPerson, LibraryPicture, LibraryView


def _picture(asset_id: str, **fields: Any) -> LibraryPicture:
    fields.setdefault("taken_at", datetime(2020, 5, 1, 12, tzinfo=UTC))
    fields.setdefault("media_kind", "photo")
    return LibraryPicture(asset_id=asset_id, **fields)


def _view(*pictures: LibraryPicture, line: float | None = None) -> LibraryView:
    return LibraryView(pictures=pictures, people={}, sharpness_line=line)


def _admitted(view: LibraryView, request: str, lexicon: Lexicon) -> set[str]:
    facts = link_facts(request, view, lexicon)
    return {picture.asset_id for picture in view.pictures if facts.admits(picture)}


def test_a_country_immich_named_on_the_pictures_links_the_request_to_them(
    lexicon: Lexicon,
) -> None:
    view = _view(
        _picture("away", city="Northvale", country="Examplia"),
        _picture("home", city="Southport", country="Otherland"),
    )

    assert _admitted(view, "I love examplia, show me the proof", lexicon) == {"away"}


def test_a_place_that_is_also_a_word_links_only_when_written_as_a_name_mid_sentence(
    lexicon: Lexicon,
) -> None:
    view = _view(
        _picture("town", city="Meadow", country="Examplia"),
        _picture("elsewhere", city="Northvale", country="Examplia"),
    )

    assert _admitted(view, "our weekends in Meadow", lexicon) == {"town"}
    assert _admitted(view, "flowers in a meadow in spring", lexicon) == {"town", "elsewhere"}
    assert _admitted(view, "Meadow weekends", lexicon) == {"town", "elsewhere"}
    assert _admitted(view, "along the years in northvale", lexicon) == {"elsewhere"}


def test_a_kind_of_picture_links_to_the_label_preparation_gave_it(lexicon: Lexicon) -> None:
    view = _view(
        _picture("app", picture_kind="screenshot_from_computer"),
        _picture("receipt", picture_kind="full_page_image"),
        _picture("trail", picture_kind="geographical_map"),
        _picture("cat", picture_kind="photograph"),
    )

    assert _admitted(view, "sport app screenshots", lexicon) == {"app"}
    assert _admitted(view, "maps and documents from our trips", lexicon) == {"receipt", "trail"}


def test_photos_named_beside_a_kind_ask_for_both(lexicon: Lexicon) -> None:
    view = _view(_picture("clip", media_kind="video"), _picture("still", picture_kind="photograph"))

    assert _admitted(view, "our holiday videos", lexicon) == {"clip"}
    assert _admitted(view, "photos and videos of the dog", lexicon) == {"clip", "still"}


def test_blurry_is_below_the_engines_own_sharpness_line(lexicon: Lexicon) -> None:
    pictures = (
        _picture("soft", sharpness=12.0),
        _picture("crisp", sharpness=50.0),
        _picture("unmeasured"),
    )
    measured = _view(*pictures, line=30.0)

    assert _admitted(measured, "best blurry pictures", lexicon) == {"soft"}
    assert _admitted(measured, "pictures of the dog in focus", lexicon) == {"crisp"}


def test_without_a_measured_line_blurry_filters_nothing_and_says_so(lexicon: Lexicon) -> None:
    unmeasured = _view(_picture("soft", sharpness=12.0), _picture("crisp", sharpness=50.0))

    facts = link_facts("best blurry pictures", unmeasured, lexicon)

    assert all(facts.admits(picture) for picture in unmeasured.pictures)
    assert any("not measured" in reason for reason in facts.reasons)


def _person(person_id: str) -> LibraryPerson:
    return LibraryPerson(person_id=person_id, name=person_id.title(), role=None, birth_date=None)


def test_faces_over_a_count_name_the_people_recognised_that_often(lexicon: Lexicon) -> None:
    often, twice = frozenset({"often"}), frozenset({"often", "twice"})
    view = LibraryView(
        pictures=(
            _picture("p1", people=twice),
            _picture("p2", people=twice),
            _picture("p3", people=often),
        ),
        people={"often": _person("often"), "twice": _person("twice")},
        sharpness_line=None,
    )

    assert link_facts("everyone in over 2 pictures", view, lexicon).people == ("often",)
    assert link_facts("people with at least 2 photos", view, lexicon).people == (
        "often",
        "twice",
    )


def test_first_last_and_farthest_ask_for_a_computed_selection(lexicon: Lexicon) -> None:
    view = _view(_picture("any"))

    assert link_facts("the first picture of each person", view, lexicon).extreme == "first"
    assert link_facts("the most recent photo of everyone", view, lexicon).extreme == "last"
    assert link_facts("the farthest I have been from home", view, lexicon).extreme == "farthest"
    assert link_facts("my son's firsts of anything new", view, lexicon).extreme is None
