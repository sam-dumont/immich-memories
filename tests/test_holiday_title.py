"""A holiday film opens on the holiday's own name and the years the cut shows.

The automatic Assumption film opened on "Été 2022–2026": `generate` never told the title
which holiday it was filming, so the template named the span as a season, with years the
film did not contain.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import build_title_settings
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import resolve_film_title, years_spanned
from immich_memories.titles.title_source import TitleSource
from tests.conftest import make_asset


def _settings(tmp_path, preset: dict, years: list[int], locale: str = "fr"):
    config = Config(title_screens={"locale": locale})
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "holiday.mp4",
        config=config,
        memory_type="holiday",
        memory_preset_params=preset,
        date_start=date(1997, 8, 13),
        date_end=date(2026, 8, 17),
    )
    clips = [AssemblyClip(path=Path(), duration=4.0, date=f"{year}-08-15") for year in years]
    return build_title_settings(params, config, clips)


def test_the_title_is_the_holidays_own_name_and_the_years_in_the_cut(tmp_path):
    settings = _settings(
        tmp_path, {"holiday": "Assumption Day", "country": "BE"}, [2015, *range(2017, 2027)]
    )

    assert settings is not None
    # The span of years in the cut, gaps not written out (owner ruling, rc.10).
    assert settings.title_override == "Assomption · 2015–2026"
    assert settings.subtitle_override is None
    assert settings.title_source is TitleSource.OCCASION


def test_a_household_day_is_named_as_the_household_wrote_it(tmp_path):
    settings = _settings(
        tmp_path,
        {"holiday": "12-06", "country": "BE", "holiday_name": "Saint-Nicolas"},
        [2024, 2025],
    )

    assert settings is not None
    assert settings.title_override == "Saint-Nicolas · 2024–2025"


@pytest.mark.parametrize(
    ("years", "written"),
    [
        ([2026], "2026"),
        ([2004, 2005, 2006], "2004–2006"),
        ([2004, 2007, 2015, 2016, 2017], "2004–2017"),
    ],
)
def test_years_are_written_as_the_span_of_the_cut(years, written):
    assert years_spanned(years) == written


def test_a_holiday_never_asks_the_model_for_its_title(tmp_path):
    asked = []
    config = Config(llm={"enabled": True, "model": "a-model"})

    title = resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[],
        config=config,
        memory_type="holiday",
        date_range=DateRange(datetime(2022, 8, 13), datetime(2026, 8, 17, 23, 59, 59)),
        person_names=[],
        memory_preset_params={"holiday": "Assumption Day"},
        ask=lambda **kwargs: asked.append(kwargs),
    )

    assert asked == []
    assert title == (None, None, None)


class _Immich:
    """The Immich HTTP API, answering a window with the videos taken in it."""

    def __init__(self, videos) -> None:
        self.videos = videos

    def get_videos_for_date_range(self, date_range) -> list:
        start, end = date_range.start.replace(tzinfo=None), date_range.end.replace(tzinfo=None)
        return [v for v in self.videos if start <= v.local_taken_at.replace(tzinfo=None) <= end]

    def require_read_permissions(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def test_generate_tells_the_film_which_holiday_it_is_and_keeps_the_day(tmp_path, monkeypatch):
    from immich_memories.cli import main

    config = tmp_path / "config.yaml"
    config.write_text("immich:\n  url: http://immich.invalid\n  api_key: not-a-real-key\n")
    day = [
        make_asset(f"day-{n}", file_created_at=datetime(2024, 8, 15, 12, n, tzinfo=UTC))
        for n in range(6)
    ]
    before = make_asset("before", file_created_at=datetime(2024, 8, 13, 12, tzinfo=UTC))
    seen: dict = {}

    def pipeline(**kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    # WHY: the Immich HTTP API is the boundary this run reads from.
    monkeypatch.setattr(
        "immich_memories.api.immich.SyncImmichClient", lambda **_kw: _Immich([*day, before])
    )
    with (
        # WHY: init_config_dir writes to the real home, which a unit test must not touch.
        patch("immich_memories.cli.init_config_dir"),
        # WHY: selection and render; this test is about what generate hands them.
        patch("immich_memories.cli.generate.run_pipeline_and_generate", side_effect=pipeline),
    ):
        result = CliRunner().invoke(
            main,
            [
                "-c",
                str(config),
                "generate",
                "--memory-type",
                "holiday",
                "--holiday",
                "08-15",
                "--year",
                "2024",
                "--years-back",
                "2",
                "--no-photos",
                "--no-live-photos",
            ],
        )

    assert result.exit_code == 0, result.output
    assert seen["memory_preset_params"]["holiday"] == "08-15"
    assert seen["memory_preset_params"]["country"] == "US"
    assert sorted(a.id for a in seen["assets"]) == sorted(a.id for a in day)
