"""Rendering a saved cut hands the engine the cut as saved, with the request's output choices."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from immich_memories.generate_saved_cut import CutRenderRequest, render_saved_cut
from immich_memories.tracking.models import RunMetadata
from tests.test_revision_render import cut  # noqa: F401 - the saved-cut fixture

RUN = RunMetadata(
    run_id="20260927_080000_cafe",
    created_at=datetime(2026, 9, 27, 8, tzinfo=UTC),
    status="completed",
    memory_type="monthly_highlights",
    date_range_start=date(2020, 1, 1),
    date_range_end=date(2020, 1, 31),
)


def _render(params, attempt, monkeypatch, request: CutRenderRequest, run: RunMetadata = RUN):
    handed = {}

    def generate_memory(given):
        handed["params"] = given
        return Path("/films/film.mp4")

    # WHY: the render writes a film with FFmpeg; the engine's own tests own that side.
    monkeypatch.setattr("immich_memories.generate_saved_cut.generate_memory", generate_memory)
    render_saved_cut(
        config=params.config,
        client=None,
        run=run,
        attempt_dir=attempt,
        revision=None,
        request=request,
    )
    return handed["params"]


def test_a_retired_quality_word_renders_at_the_preset_it_now_means(cut, monkeypatch):  # noqa: F811
    params, attempt = cut
    params.config.output.crf = 18

    handed = _render(params, attempt, monkeypatch, CutRenderRequest(quality="medium"))

    # `generate --quality medium` means balanced since the presets were renamed; the CRF
    # comes from the preset again, as when generate is given --quality.
    assert handed.config.output.quality == "balanced"
    assert handed.config.output.crf is None


def test_the_cut_is_rendered_as_saved_with_the_request_s_title(cut, monkeypatch):  # noqa: F811
    params, attempt = cut

    handed = _render(
        params, attempt, monkeypatch, CutRenderRequest(title="Winter", llm_title=False)
    )

    assert [c.asset.id for c in handed.clips] == [c.asset.id for c in params.clips]
    assert handed.title == "Winter"
    assert handed.editorial_attempt_dir == attempt


def test_the_render_keeps_the_title_and_memory_generate_worked_out_for_the_cut(cut, monkeypatch):  # noqa: F811
    from datetime import date as day

    from immich_memories.processing.render_inputs import write_cut_titles
    from immich_memories.titles.title_source import TitleSource

    params, attempt = cut
    # A special day is named from its catalogue entry when the cut is made; a render made later
    # must not fall back to the month ("Janvier 2016").
    write_cut_titles(
        attempt,
        title="Le marathon",
        subtitle="1 janvier 2016",
        source=TitleSource.OCCASION,
        preset_params={"trip_start": day(2016, 1, 1), "location_name": "Bruges"},
    )

    handed = _render(params, attempt, monkeypatch, CutRenderRequest())

    assert (handed.title, handed.subtitle) == ("Le marathon", "1 janvier 2016")
    assert handed.title_source == TitleSource.OCCASION.value
    assert handed.memory_preset_params == {"trip_start": day(2016, 1, 1), "location_name": "Bruges"}


@pytest.mark.parametrize("kept", [None, {"hemisphere": "north"}], ids=["no-titles", "no-holiday"])
def test_an_old_holiday_cut_renders_its_holiday_title(cut, monkeypatch, kept):  # noqa: F811
    # WHY: a holiday cut made before cuts kept their holiday re-rendered as "From December 2021
    # to December 2025" (#2573); the holiday is read back from the window it was built around.
    from immich_memories.processing.render_inputs import write_cut_titles

    params, attempt = cut
    if kept is not None:
        write_cut_titles(attempt, title=None, subtitle=None, source=None, preset_params=kept)
    christmas = replace(
        RUN,
        memory_type="holiday",
        date_range_start=date(2021, 12, 23),
        date_range_end=date(2025, 12, 27),
    )

    handed = _render(params, attempt, monkeypatch, CutRenderRequest(), run=christmas)

    assert handed.title.startswith("Christmas · ")
    assert handed.subtitle is None
    assert handed.memory_preset_params["holiday"] == "christmas"


@pytest.mark.parametrize(
    "kept_title",
    [None, ("Été 2022-2026", "model"), ("Été 2022-2026", "fallback")],
    ids=["no-title", "model-title", "template-title"],
)
def test_an_old_multi_year_holiday_cut_renders_its_holiday_over_the_years_it_shows(
    cut,  # noqa: F811
    monkeypatch,
    kept_title,
):
    # WHY: an Assumption Day cut made by automation before cuts kept their holiday, over
    # several yearly windows, re-rendered as "Été 2022-2026": its kept title was a season,
    # and its parameters said no holiday. The window says which holiday it was built around.
    from immich_memories.processing.render_inputs import write_cut_titles

    params, attempt = cut
    params.config.title_screens.locale = "fr"
    title, source = kept_title or (None, None)
    write_cut_titles(attempt, title=title, subtitle=None, source=source, preset_params={})
    # WHY: the home country comes from Immich's geodata, the one network boundary here.
    monkeypatch.setattr(
        "immich_memories.memory_types.holiday_params.home_country", lambda _config: "BE"
    )
    assumption = replace(
        RUN,
        memory_type="holiday",
        date_range_start=date(2022, 8, 13),
        date_range_end=date(2026, 8, 17),
    )

    handed = _render(params, attempt, monkeypatch, CutRenderRequest(), run=assumption)

    # The cut's clips were taken from 2020 to 2023: the years it shows, with an en dash.
    assert handed.title == "Assomption · 2020\u20132023"
    assert handed.memory_preset_params["holiday"] == "Assumption Day"


def test_a_typed_title_on_an_old_holiday_cut_stands(cut, monkeypatch):  # noqa: F811
    from immich_memories.processing.render_inputs import write_cut_titles

    params, attempt = cut
    write_cut_titles(
        attempt, title="Our Augusts", subtitle=None, source="override", preset_params={}
    )
    assumption = replace(
        RUN,
        memory_type="holiday",
        date_range_start=date(2021, 12, 23),
        date_range_end=date(2025, 12, 27),
    )

    handed = _render(params, attempt, monkeypatch, CutRenderRequest(), run=assumption)

    assert handed.title == "Our Augusts"


def test_a_title_typed_at_render_still_wins(cut, monkeypatch):  # noqa: F811
    from immich_memories.processing.render_inputs import write_cut_titles

    params, attempt = cut
    write_cut_titles(attempt, title="Le marathon", subtitle=None, source=None, preset_params={})

    handed = _render(params, attempt, monkeypatch, CutRenderRequest(title="Winter"))

    assert handed.title == "Winter"


@pytest.mark.parametrize(("default", "override"), [("white", "black"), ("black", "white")])
def test_fade_override_affects_this_render_without_changing_the_saved_default(
    cut,  # noqa: F811
    monkeypatch,
    default,
    override,
):
    params, attempt = cut

    params.config.title_screens.fade_color = default
    handed = _render(params, attempt, monkeypatch, CutRenderRequest(fade_color=override))

    assert handed.config.title_screens.fade_color == override
    assert params.config.title_screens.fade_color == default
    next_film = _render(params, attempt, monkeypatch, CutRenderRequest())
    assert next_film.config.title_screens.fade_color == default


@pytest.mark.parametrize(
    "style", ["modern_warm", "elegant_minimal", "vintage_charm", "playful_bright", "soft_romantic"]
)
def test_named_title_style_loads_and_overrides_only_this_render(cut, monkeypatch, style):  # noqa: F811
    from immich_memories.config.models.render import TitleScreenConfig

    assert TitleScreenConfig(style_mode=style).style_mode == style
    params, attempt = cut
    handed = _render(params, attempt, monkeypatch, CutRenderRequest(title_style=style))
    assert handed.config.title_screens.style_mode == style
    assert params.config.title_screens.style_mode == "auto"


def test_an_album_film_renders_under_the_name_generate_gave_it(cut, monkeypatch):  # noqa: F811
    params, attempt = cut
    album_run = replace(
        RUN,
        memory_type="album",
        output_path=f"/films/album_trip_2025_{RUN.run_id}/album_trip_2025_deadbeef.mp4",
    )
    handed = {}

    def generate_memory(given):
        handed["params"] = given
        return Path("/films/film.mp4")

    # WHY: the render writes a film with FFmpeg; the engine's own tests own that side.
    monkeypatch.setattr("immich_memories.generate_saved_cut.generate_memory", generate_memory)
    render_saved_cut(
        config=params.config,
        client=None,
        run=album_run,
        attempt_dir=attempt,
        revision=None,
        request=CutRenderRequest(),
    )

    # Not all_album_<year>: one album, one name, whichever command rendered it.
    assert handed["params"].output_path.name.startswith("album_trip_2025_")


def test_an_album_cut_rendered_for_the_first_time_is_named_after_its_album(cut, monkeypatch):  # noqa: F811
    from immich_memories.processing.render_inputs import write_cut_titles

    params, attempt = cut
    # `generate --no-render` kept no film, so nothing names the film but the cut's own album.
    write_cut_titles(
        attempt,
        title="First film",
        subtitle=None,
        source=None,
        preset_params={"album_id": "a1", "album_name": "First Film Trial"},
    )
    album_run = replace(RUN, memory_type="album", output_path=None)
    handed = {}

    def generate_memory(given):
        handed["params"] = given
        return Path("/films/film.mp4")

    # WHY: the render writes a film with FFmpeg; the engine's own tests own that side.
    monkeypatch.setattr("immich_memories.generate_saved_cut.generate_memory", generate_memory)
    render_saved_cut(
        config=params.config,
        client=None,
        run=album_run,
        attempt_dir=attempt,
        revision=None,
        request=CutRenderRequest(),
    )

    assert re.fullmatch(
        r"album_first_film_trial_[0-9a-f]{8}\.mp4", handed["params"].output_path.name
    )


def test_muting_is_a_render_choice_and_leaves_the_saved_cut_intact(cut, monkeypatch):  # noqa: F811
    params, attempt = cut
    muted = _render(params, attempt, monkeypatch, CutRenderRequest(original_audio=False))
    assert muted.original_audio is False
    assert [c.asset.id for c in muted.clips] == [c.asset.id for c in params.clips]
    assert _render(params, attempt, monkeypatch, CutRenderRequest()).original_audio is True
