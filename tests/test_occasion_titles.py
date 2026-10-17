"""Recurring occasions name the day, not the span between search windows."""

from datetime import date

import pytest

from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import build_title_settings
from immich_memories.titles.text_builder import generate_title, infer_selection_type


def test_on_this_day_opening_is_one_day_across_years():
    start, end = date(2020, 6, 15), date(2024, 6, 15)
    selection = infer_selection_type(memory_type="on_this_day", start_date=start, end_date=end)
    title = generate_title(selection, start_date=start, end_date=end)
    assert (title.main_title, title.subtitle) == ("June 15", "Through the Years")


def test_holiday_opening_names_the_occasion(tmp_path):
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "holiday.mp4",
        config=Config(),
        memory_type="holiday",
        memory_preset_params={"holiday": "christmas"},
        date_start=date(2020, 12, 23),
        date_end=date(2024, 12, 27),
    )
    settings = build_title_settings(params, params.config, [])
    assert settings is not None
    # No cut yet, so no years: the name stands alone, and no subtitle repeats the span.
    assert settings.title_override == "Christmas"
    assert settings.subtitle_override is None

    params.title, params.subtitle = "Our Christmases", "2020–2024"
    settings = build_title_settings(params, params.config, [])
    assert settings.title_override == "Our Christmases"
    assert settings.subtitle_override == "2020–2024"


def test_a_holiday_that_lost_its_parameter_is_not_called_christmas(tmp_path):
    """No occasion beats the wrong occasion on the one screen every viewer sees."""
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "holiday.mp4",
        config=Config(),
        memory_type="holiday",
        memory_preset_params={},
        date_start=date(2020, 12, 23),
        date_end=date(2024, 12, 27),
    )

    settings = build_title_settings(params, params.config, [])

    assert settings is not None
    assert settings.title_override is None


def _on_this_day_span(day: date):
    """The span `generate --memory-type on_this_day --day <day>` records for its film."""
    from immich_memories.memory_types.date_builders import build_on_this_day
    from immich_memories.timeperiod import DateRange

    windows = build_on_this_day(day)
    return DateRange(start=windows[-1].start, end=windows[0].end)


@pytest.mark.parametrize(
    ("locale", "day", "named"),
    [
        ("en", date(2026, 10, 15), "October 15"),
        ("fr", date(2026, 10, 15), "15 octobre"),
        ("en", date(2026, 11, 1), "November 1"),
        ("fr", date(2026, 11, 1), "1 novembre"),
        ("fr", date(2027, 1, 1), "1 janvier"),
    ],
)
def test_on_this_day_is_titled_with_the_anniversary_not_the_padded_window(
    tmp_path, locale, day, named
):
    """Each year's window starts the day before; the film is still about the day asked for."""
    from immich_memories.operations.film_labelling import label_for_cut
    from immich_memories.titles.film_title import static_title, template_title

    config = Config(title_screens={"locale": locale})
    span = _on_this_day_span(day)
    kept = static_title(
        config, memory_type="on_this_day", date_range=span, person_name=None, years={2019, 2025}
    )
    assert kept == f"{named} · 2019–2025"
    assert (
        template_title(config, memory_type="on_this_day", date_range=span, person_name=None)[0]
        == named
    )

    # The title screen the render draws when no title was kept.
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=config,
        memory_type="on_this_day",
        date_start=span.start.date(),
        date_end=span.end.date(),
    )
    settings = build_title_settings(params, config, [])
    selection = infer_selection_type(
        memory_type="on_this_day", start_date=settings.start_date, end_date=settings.end_date
    )
    screen = generate_title(
        selection, start_date=settings.start_date, end_date=settings.end_date, locale=locale
    )
    assert screen.main_title == named

    # The Immich description of a film whose cut kept no title.
    label = label_for_cut(
        config,
        memory_type="on_this_day",
        date_start=span.start,
        date_end=span.end,
        attempt_dir=None,
    )
    assert label is not None
    assert label.description.startswith(named)
