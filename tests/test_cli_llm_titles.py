"""Who names a memory on the CLI, and with what.

A film about people or an occasion is named by the model as soon as a reader is
configured: a date span with three full names under it describes no film. Trips
keep their own prompt and still wait to be asked, and `--no-llm-title` pins the
template for a matrix run that has to stay comparable across months.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from immich_memories.api.album_service import AlbumService, FilmScope
from immich_memories.api.models import Asset, AssetType, ExifInfo, VideoClipInfo
from immich_memories.config_loader import Config
from immich_memories.i18n import SUPPORTED_LOCALES
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import resolve_film_title
from tests.conftest import make_clip


def _clip_at(**exif: str) -> VideoClipInfo:
    """A clip whose only distinguishing EXIF is the place field(s) given."""
    now = datetime(2025, 7, 1)
    asset = Asset(
        id="clip-at-place",
        type=AssetType.VIDEO,
        fileCreatedAt=now,
        fileModifiedAt=now,
        updatedAt=now,
        originalFileName="VID_clip-at-place.MOV",
        exifInfo=ExifInfo(**exif),
        duration="0:00:05.000",
    )
    return VideoClipInfo(
        asset=asset, width=1920, height=1080, duration_seconds=5.0, bitrate=10_000_000, codec="hevc"
    )


def _clip_in(city: str) -> VideoClipInfo:
    """A clip whose only distinguishing EXIF is the city it was taken in."""
    return _clip_at(city=city)


_RANGE = DateRange(start=datetime(2025, 7, 1), end=datetime(2025, 7, 14))


def _config_with_llm() -> Config:
    return Config(
        tier="full", llm={"enabled": True, "base_url": "http://llm.test/v1", "model": "some-model"}
    )


def _answers(title: str = "Ada and her grandparents", subtitle: str | None = None):
    """Stand in for the reader. WHY: the LLM call is the only boundary here."""
    seen: dict = {}

    def ask(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(title=title, subtitle=subtitle)

    return ask, seen


def test_a_people_memory_is_named_by_the_model_with_no_flag_at_all() -> None:
    """A reader is configured, so the family record beats the name list."""
    ask, seen = _answers()

    title, subtitle, _source = resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="multi_person",
        date_range=_RANGE,
        person_names=["Ada Example", "Grace Example"],
        ask=ask,
    )

    assert (title, subtitle) == ("Ada and her grandparents", None)
    assert seen["person_names"] == ["Ada Example", "Grace Example"]


def test_no_llm_title_pins_the_template() -> None:
    """The contact-sheet matrix needs runs before and after to stay comparable."""
    called = []

    title, subtitle, _source = resolve_film_title(
        enabled=False,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="multi_person",
        date_range=_RANGE,
        person_names=["Ada Example"],
        ask=lambda **kwargs: called.append(kwargs),
    )

    assert (title, subtitle) == (None, None)
    assert called == []


def test_requesting_a_title_without_a_model_explains_the_template_fallback(caplog) -> None:
    called = []
    title, subtitle, source = resolve_film_title(
        enabled=True,
        title_override=None,
        subtitle_override="Summer",
        clips=[make_clip("clip-1")],
        config=Config(tier="nas"),
        memory_type="multi_person",
        date_range=_RANGE,
        person_names=[],
        # WHY: fail visibly if a missing model still reaches the external LLM boundary.
        ask=lambda **kwargs: called.append(kwargs),
    )

    assert (title, subtitle, source) == (None, "Summer", None)
    assert called == []
    assert "--llm-title needs a configured LLM; using the template title" in caplog.text


def test_a_trip_still_waits_to_be_asked() -> None:
    """Trips keep the prompt they have; this PR does not change what names them."""
    called = []

    title, _subtitle, _source = resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="trip",
        date_range=_RANGE,
        person_names=[],
        ask=lambda **kwargs: called.append(kwargs),
    )

    assert title is None
    assert called == []


def test_the_flag_forces_the_model_onto_a_trip() -> None:
    ask, seen = _answers(title="Under the sandstone cliffs")

    title, _subtitle, _source = resolve_film_title(
        enabled=True,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="trip",
        date_range=_RANGE,
        person_names=[],
        ask=ask,
    )

    assert title == "Under the sandstone cliffs"
    assert seen["memory_type"] == "trip"


def test_an_explicit_title_outranks_the_model() -> None:
    """--title is the user typing the answer; nothing should overrule it."""
    called = []

    title, subtitle, _source = resolve_film_title(
        enabled=True,
        title_override="Our Summer",
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="year_in_review",
        date_range=_RANGE,
        person_names=[],
        ask=lambda **kwargs: called.append(kwargs),
    )

    assert title == "Our Summer"
    assert called == []


def test_the_grouped_condition_travels_with_the_names() -> None:
    """Either grandparent AND the child is a shape, not a list of three names."""
    ask, seen = _answers()

    resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="multi_person",
        date_range=_RANGE,
        person_names=["Ada Example", "Grace Example"],
        memory_preset_params={
            "person_expression": {
                "all": [
                    {"person": "Ada Example"},
                    {"person": "Grace Example"},
                ]
            }
        },
        ask=ask,
    )

    assert seen["facts"].people_condition == '("Ada Example" AND "Grace Example")'


def test_a_catalogued_day_hands_the_model_what_the_catalogue_saw() -> None:
    ask, seen = _answers(title="A day at the bowling alley")

    resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"what": "an afternoon at a themed bowling alley"},
        ask=ask,
    )

    assert seen["facts"].occasion_name == "an afternoon at a themed bowling alley"


def _config_with_llm_locale(locale: str) -> Config:
    return Config(
        tier="full",
        llm={"enabled": True, "base_url": "http://llm.test/v1", "model": "some-model"},
        title_screens={"locale": locale},
    )


def test_a_special_days_catalogue_title_is_reworded_by_the_model_not_shown_verbatim() -> None:
    """Case 16/18 of #1954: locale fr, a catalogue title banked in English (#1959).

    The catalogue's title travels in through the same slot a typed --title
    uses (see `name_from_catalogue`), but a special day's row is not a
    person's own words -- it is an English fact from the scan, and the film
    must still open on a French headline.
    """
    ask, seen = _answers(title="Une journée au bowling")

    title, subtitle, source = resolve_film_title(
        enabled=None,
        title_override="A day at the bowling alley",
        subtitle_override="Someone's first strike",
        clips=[make_clip("clip-1")],
        config=_config_with_llm_locale("fr"),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={
            "title": "A day at the bowling alley",
            "subtitle": "Someone's first strike",
        },
        ask=ask,
    )

    assert (title, subtitle) == ("Une journée au bowling", None)
    assert source is not None and source.value == "model"
    assert seen["locale"] == "fr"
    assert "A day at the bowling alley" in seen["facts"].occasion_name
    assert "Someone's first strike" in seen["facts"].occasion_name


def test_a_special_day_with_no_model_falls_back_to_the_place_in_french() -> None:
    """With no reader configured, the catalogue's English title cannot be
    reworded, so the film opens on where the day was instead, with the
    year it would otherwise lose riding in the subtitle."""
    called = []

    title, subtitle, source = resolve_film_title(
        enabled=None,
        title_override="A day in Paris",
        subtitle_override="",
        clips=[_clip_in("Paris")],
        config=Config(tier="nas", title_screens={"locale": "fr"}),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"title": "A day in Paris", "subtitle": ""},
        ask=lambda **kwargs: called.append(kwargs),
    )

    assert (title, subtitle) == ("Une journée à Paris", "1 juillet 2025")
    assert source is not None and source.value == "fallback"
    assert called == []


def test_an_english_film_keeps_the_catalogues_english_title_verbatim() -> None:
    """The catalogue is always English (#1959): for an English film there is
    nothing to reword and no reason to replace it with a place fallback."""
    called = []

    title, subtitle, source = resolve_film_title(
        enabled=None,
        title_override="A day in Lisbon",
        subtitle_override="",
        clips=[_clip_in("Lisbon")],
        config=Config(tier="nas", title_screens={"locale": "en"}),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"title": "A day in Lisbon", "subtitle": ""},
        ask=lambda **kwargs: called.append(kwargs),
    )

    assert (title, subtitle) == ("A day in Lisbon", "")
    assert source is not None and source.value == "occasion"
    assert called == []


@pytest.mark.parametrize("locale", [loc for loc in SUPPORTED_LOCALES if loc != "en"])
def test_a_special_day_with_no_model_is_placed_in_every_non_english_locale(locale: str) -> None:
    """The rules path never shows the catalogue's English title, in any of
    the 13 other supported film languages, and always keeps the year."""
    title, subtitle, source = resolve_film_title(
        enabled=None,
        title_override="A day in Lisbon",
        subtitle_override="",
        clips=[_clip_in("Lisbon")],
        config=Config(tier="nas", title_screens={"locale": locale}),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"title": "A day in Lisbon", "subtitle": ""},
        ask=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no model is configured")),
    )

    assert title is not None and title != "A day in Lisbon"
    assert subtitle  # the year the title's own words no longer carry
    assert source is not None and source.value == "fallback"


def test_an_explicit_cli_title_still_wins_verbatim_on_a_special_day() -> None:
    """A typed --title is not the catalogue's, and must not be sent through
    the occasion prompt or replaced by a place fallback."""
    called = []

    title, subtitle, source = resolve_film_title(
        enabled=None,
        title_override="Grandma's 80th",
        subtitle_override=None,
        clips=[_clip_in("Paris")],
        config=_config_with_llm_locale("fr"),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"title": "A day at the bowling alley"},
        ask=lambda **kwargs: called.append(kwargs),
    )

    assert (title, subtitle) == ("Grandma's 80th", None)
    assert source is not None and source.value == "override"
    assert called == []


def test_the_occasion_fact_keeps_both_the_catalogues_title_and_its_description() -> None:
    """The catalogue's title is the vetted name; `what` is the plainer
    description banked alongside it (#1985 review). Neither should drop
    the other -- a title with no description behind it is as thin a fact
    as a description with no name."""
    ask, seen = _answers(title="Une journée au bowling")

    resolve_film_title(
        enabled=None,
        title_override="A day at the bowling alley",
        subtitle_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm_locale("fr"),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={
            "title": "A day at the bowling alley",
            "what": "an afternoon at a themed bowling alley",
        },
        ask=ask,
    )

    assert "A day at the bowling alley" in seen["facts"].occasion_name
    assert "an afternoon at a themed bowling alley" in seen["facts"].occasion_name


def test_a_model_failure_falls_back_to_the_place_not_the_month_year_template() -> None:
    """An exception from the reader must not drop the occasion for a date card."""

    def failing_ask(**_kwargs):
        raise RuntimeError("boom")

    title, subtitle, source = resolve_film_title(
        enabled=None,
        title_override="A day at the bowling alley",
        subtitle_override="",
        clips=[_clip_in("Paris")],
        config=_config_with_llm_locale("fr"),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"title": "A day at the bowling alley", "subtitle": ""},
        ask=failing_ask,
    )

    assert title == "Une journée à Paris"
    assert subtitle
    assert source is not None and source.value == "fallback"


def test_a_refused_title_falls_back_to_the_place_not_the_month_year_template() -> None:
    """The reader answering with nothing (a year-guard rejection, or simply
    no answer) must not drop the occasion for a date card either."""
    title, subtitle, source = resolve_film_title(
        enabled=None,
        title_override="A day at the bowling alley",
        subtitle_override="",
        clips=[_clip_in("Paris")],
        config=_config_with_llm_locale("fr"),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"title": "A day at the bowling alley", "subtitle": ""},
        ask=lambda **_kwargs: None,
    )

    assert title == "Une journée à Paris"
    assert subtitle
    assert source is not None and source.value == "fallback"


@pytest.mark.parametrize(
    ("exif_field", "place_value", "expected_title"),
    [
        ("city", "Paris", "Une journée à Paris"),
        ("state", "Bavaria", "Une journée en Bavière"),
        ("country", "France", "Une journée en France"),
    ],
)
def test_the_place_title_grammar_in_french(
    exif_field: str, place_value: str, expected_title: str
) -> None:
    """A city, a region and a country each take their own French preposition
    (#1985 review): none of them is "à", and a hard-coded one was the bug."""
    title, _subtitle, _source = resolve_film_title(
        enabled=None,
        title_override="A day somewhere",
        subtitle_override="",
        clips=[_clip_at(**{exif_field: place_value})],
        config=Config(tier="nas", title_screens={"locale": "fr"}),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"title": "A day somewhere", "subtitle": ""},
        ask=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no model is configured")),
    )

    assert title == expected_title


@pytest.mark.parametrize("locale", [loc for loc in SUPPORTED_LOCALES if loc not in {"en", "fr"}])
def test_a_country_place_title_is_localised_in_every_supported_locale(locale: str) -> None:
    """A country name is never left in English (other than for the English
    film, which keeps the catalogue verbatim and never reaches this fallback
    at all -- see the English-film test, and French, which is covered by the
    French grammar test above and happens to spell "France" the English way):
    either a grammatically inflected phrase ("we Francji") or the plain CLDR
    name in the neutral form."""
    title, _subtitle, _source = resolve_film_title(
        enabled=None,
        title_override="A day somewhere",
        subtitle_override="",
        clips=[_clip_at(country="France")],
        config=Config(tier="nas", title_screens={"locale": locale}),
        memory_type="special_day",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"title": "A day somewhere", "subtitle": ""},
        ask=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no model is configured")),
    )

    assert title is not None
    assert "France" not in title


def test_the_album_the_cut_sits_in_reaches_the_facts() -> None:
    """WHY the lambda: it stands in for the Immich album read, the only boundary."""
    ask, seen = _answers()

    resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="multi_person",
        date_range=_RANGE,
        person_names=["Ada Example"],
        album_lookup=lambda: "Sunday at the lake",
        ask=ask,
    )

    assert seen["facts"].album_name == "Sunday at the lake"


def test_a_year_film_in_the_phone_catch_all_gets_its_normal_title_facts() -> None:
    """121 of 127 pictures in a library-scale catch-all: the model hears no album name."""
    cut = [f"p{n:03d}" for n in range(127)]
    everything = {
        "id": "album-everything",
        "albumName": "Everything",
        "assetCount": 38_000,
        "startDate": "2014-02-01T09:00:00.000Z",
        "endDate": "2026-09-20T18:00:00.000Z",
    }

    async def request(method: str, endpoint: str, **kwargs):
        # WHY: stands in for Immich's `GET /albums?assetId=` read, the only boundary.
        return [everything] if kwargs["params"]["assetId"] in cut[:121] else []

    async def version():  # pragma: no cover - never reached
        raise AssertionError

    service = AlbumService(request, version)
    year = DateRange(start=datetime(2024, 1, 1), end=datetime(2024, 12, 31, 23, 59))
    scope = FilmScope(start=year.start, end=year.end, pool=3500)
    ask, seen = _answers(title="2024")

    title, _subtitle, _source = resolve_film_title(
        enabled=True,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="year",
        date_range=year,
        person_names=[],
        album_lookup=lambda: asyncio.run(service.album_holding_most(cut, scope=scope)),
        ask=ask,
    )

    assert seen["facts"].album_name is None
    assert title == "2024"


def test_an_album_memory_never_pays_for_the_lookup() -> None:
    """Its own name is already known; one request per asset is not free."""
    asked = []

    resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="album",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"album_name": "Old Negatives 75"},
        album_lookup=lambda: asked.append("asked") or "Something Else",
        ask=_answers()[0],
    )

    assert asked == []


def test_an_unanswerable_album_lookup_leaves_the_rest_of_the_facts_alone() -> None:
    ask, seen = _answers()

    def explode() -> str:
        raise RuntimeError("Immich is down")

    resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="multi_person",
        date_range=_RANGE,
        person_names=["Ada Example"],
        album_lookup=explode,
        ask=ask,
    )

    assert seen["facts"].album_name is None
    assert seen["person_names"] == ["Ada Example"]


def test_the_model_answering_without_a_subtitle_leaves_no_subtitle_line() -> None:
    """Null beats a guess: the name list must not come back as a consolation."""
    ask, _seen = _answers(subtitle=None)

    title, subtitle, _source = resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=_config_with_llm(),
        memory_type="multi_person",
        date_range=_RANGE,
        person_names=["Ada Example", "Grace Example"],
        ask=ask,
    )

    assert (title, subtitle) == ("Ada and her grandparents", None)


def test_the_flag_carries_the_clip_descriptions_into_the_ask() -> None:
    """The analyzer already described every selected clip; a trip prompt gets them."""
    ask, seen = _answers(title="A Fortnight in July", subtitle="2025")

    clip = make_clip("clip-1")
    clip.llm_description = "children running through a sprinkler"

    title, subtitle, _source = resolve_film_title(
        enabled=True,
        title_override=None,
        clips=[clip],
        config=_config_with_llm(),
        memory_type="trip",
        date_range=_RANGE,
        person_names=["Ada Example"],
        ask=ask,
    )

    assert (title, subtitle) == ("A Fortnight in July", "2025")
    assert seen["clip_descriptions"] == ["children running through a sprinkler"]
    assert seen["person_names"] == ["Ada Example"]
    assert seen["duration_days"] == 13


def test_nas_selection_can_use_a_configured_llm_for_its_title() -> None:
    """A CPU selection does not prevent an explicitly requested text-only title."""
    asked = []

    # WHY: title generation crosses the external LLM boundary.
    def ask(**kwargs):
        asked.append(kwargs)
        return SimpleNamespace(title="A Fortnight Together", subtitle="2025")

    title, _subtitle, _source = resolve_film_title(
        enabled=True,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=Config(
            tier="nas", llm={"enabled": True, "base_url": "http://llm.test/v1", "model": "m"}
        ),
        memory_type="multi_person",
        date_range=_RANGE,
        person_names=["Ada Example"],
        ask=ask,
    )

    assert title == "A Fortnight Together"
    assert len(asked) == 1


def test_a_missing_reader_leaves_the_template_alone() -> None:
    """A people memory without a model configured must not fail the run."""
    title, subtitle, _source = resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=Config(),
        memory_type="multi_person",
        date_range=_RANGE,
        person_names=["Ada Example"],
        ask=lambda **_kwargs: None,
    )

    assert (title, subtitle) == (None, None)


def test_a_plan_that_stops_before_rendering_still_shows_the_title(capsys) -> None:
    """--no-render answers "what will this film be called" without rendering it."""
    from pathlib import Path

    from immich_memories.cli._generation_preview import GenerationPreview, print_generation_preview
    from immich_memories.processing.output_canvas import OutputCanvas
    from immich_memories.processing.timeline_budget import TimelinePlan

    print_generation_preview(
        GenerationPreview(
            memory_type="special_day",
            date_range="Mar 27",
            video_candidates=1,
            live_photo_candidates=0,
            photo_candidates=9,
            selected_videos=1,
            selected_photos=9,
            selected_duration=40.0,
            timeline=TimelinePlan(
                target_duration=60.0,
                content_budget=50.0,
                title_budget=9.5,
                title_duration=3.5,
                ending_duration=4.0,
                divider_duration=2.0,
                max_dividers=1,
                transition_budget=4.0,
            ),
            canvas=OutputCanvas(width=1280, height=720, orientation="landscape"),
            output_path=Path("/day.mp4"),
            upload_intent=False,
            music_policy="disabled",
            title="Lakeside Half 2022",
            subtitle="Ten kilometres of rain",
        )
    )

    printed = capsys.readouterr().out
    assert "Lakeside Half 2022" in printed
    assert "Ten kilometres of rain" in printed


def test_titles_use_the_shared_llm_configuration():
    config = _config_with_llm()
    ask, seen = _answers()
    resolve_film_title(
        enabled=True,
        title_override=None,
        clips=[],
        config=config,
        memory_type="year",
        date_range=_RANGE,
        person_names=[],
        ask=ask,
    )
    assert seen["llm_config"] is config.llm
    assert "title_llm" not in Config.model_fields
