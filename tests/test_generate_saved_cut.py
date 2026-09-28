"""Rendering a saved cut hands the engine the cut as saved, with the request's output choices."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

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


def _render(params, attempt, monkeypatch, request: CutRenderRequest):
    handed = {}

    def generate_memory(given):
        handed["params"] = given
        return Path("/films/film.mp4")

    # WHY: the render writes a film with FFmpeg; the engine's own tests own that side.
    monkeypatch.setattr("immich_memories.generate_saved_cut.generate_memory", generate_memory)
    render_saved_cut(
        config=params.config,
        client=None,
        run=RUN,
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


def test_a_title_typed_at_render_still_wins(cut, monkeypatch):  # noqa: F811
    from immich_memories.processing.render_inputs import write_cut_titles

    params, attempt = cut
    write_cut_titles(attempt, title="Le marathon", subtitle=None, source=None, preset_params={})

    handed = _render(params, attempt, monkeypatch, CutRenderRequest(title="Winter"))

    assert handed.title == "Winter"
