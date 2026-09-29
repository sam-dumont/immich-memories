"""A curated subject pool: the pictures were chosen for the film's written subject.

Owner ruling 2026-09-28: a picture from a request's own pool stands on the subject; its standing
score can't veto it, and allocation funds every year that holds pool pictures. Reported in the
run record, never silently.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime

import pytest

from immich_memories.analysis.annotation_lines import AssetAnnotationLine
from immich_memories.analysis.editorial_intent import build_editorial_intent
from immich_memories.analysis.editorial_product_brief import build_editorial_brief
from immich_memories.analysis.editorial_shareability import FlagRow
from immich_memories.analysis.editorial_story_standing import StandingGate
from immich_memories.timeperiod import DateRange
from tests.editorial_film_fixtures import HOME, Day, film_source

SUBJECT = "Bread making along the years"
BREAD = "A loaf of sourdough bread cooling on a wire rack on a kitchen counter."
YEARS = (2019, 2020, 2021, 2022)


def _bread_pool(tmp_path, *, pool_is_subject: bool, held_year: int | None = None):
    """Two baking days a year over four years, two pictures a day: loaves, nobody in them.

    Every picture of `held_year` carries an exposure flag, which a shareable film holds; with
    strict sharing, the rest is cleared by its clean detector heads.
    """
    days = [
        Day(date(year, month, 14), f"Baking {year}-{month:02d}", HOME)
        for year in YEARS
        for month in (3, 10)
    ]
    source = film_source(
        tmp_path,
        days,
        seconds=40,
        span=(date(YEARS[0], 1, 1), date(YEARS[-1], 12, 31)),
        product="album",
        pictures=2,
    )
    for asset_id, row in list(source.audience_annotations.items()):
        line = f"{row.text.split(' | ')[0]} | {BREAD} | at Hometown, Homeland"
        source.annotations[asset_id] = line
        source.audience_annotations[asset_id] = AssetAnnotationLine(
            asset_id,
            line,
            description=BREAD,
            heads=(
                ("nsfw_marqo", "no"),
                ("people", "none"),
                ("location", "indoor"),
                ("frame_kind", "lone_everyday_object"),
            ),
        )
    # An album is one span, from its first picture to its last.
    taken = [asset.file_created_at for asset in source.assets.values()]
    ranges = (DateRange(min(taken), max(taken)),)
    brief = build_editorial_brief("album", ranges, base=SUBJECT)
    pool_subject = SUBJECT if pool_is_subject else None
    case = replace(source.case, ranges=ranges, brief=brief, pool_subject=pool_subject)
    intent = build_editorial_intent(
        "album",
        ranges,
        brief=brief,
        material={when.date() for when in taken},
        pool_subject=pool_subject,
    )
    flags = {
        asset_id: (FlagRow(asset_id, "review", "exposure=partial", "exposure"),)
        for asset_id, asset in source.assets.items()
        if asset.file_created_at.year == held_year
    }
    if flags:
        # The NAS tier's detector heads clear a shareable film's clean pictures under strict sharing.
        source.config.editorial.preparation.tier = "no_captions"
        source.config.editorial.strict_sharing = True
    return replace(
        source,
        case=case,
        intent=intent,
        audience="shareable" if flags else source.audience,
        shareability_flags=flags,
    )


def _no_model_plan(source) -> dict:
    from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
    from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
    from immich_memories.analysis.editorial_structure_planner import plan_structure

    return plan_structure(
        source,
        StructurePlannerPorts(
            judge=NoModelJudge(),
            # WHY: no preview hashes in a fixture library; the duplicate review has nothing to read.
            thumbnail_hash=lambda _asset: None,
            rules=RuleStructureReader(source),
        ),
    ).plan


def _story_selection(source) -> dict:
    record = source.artifact_dir / "derived-decisions" / "story-selection.private.json"
    return json.loads(record.read_text())


def test_a_bread_pool_has_a_shot_in_every_year_it_holds(tmp_path):
    source = _bread_pool(tmp_path, pool_is_subject=True)

    plan = _no_model_plan(source)

    years = {datetime.fromisoformat(c["taken"]).year for c in plan["carriers"]}
    assert years == set(YEARS)


def test_a_loaf_of_the_pool_is_not_filler(tmp_path):
    source = _bread_pool(tmp_path, pool_is_subject=True)

    plan = _no_model_plan(source)

    days = {c["taken"][:10] for c in plan["carriers"]}
    assert len(days) == len(YEARS) * 2


def test_the_run_record_names_every_shot_that_stood_on_the_subject(tmp_path):
    source = _bread_pool(tmp_path, pool_is_subject=True)

    plan = _no_model_plan(source)

    stood = _story_selection(source)["stood_on_subject"]
    assert {row["asset_id"] for row in stood} == {c["asset_id"] for c in plan["carriers"]}
    assert all(row["standing"] == 0 and "subject" in row["reason"] for row in stood)


def test_an_audience_hold_still_takes_a_pool_picture(tmp_path):
    source = _bread_pool(tmp_path, pool_is_subject=True, held_year=2020)

    plan = _no_model_plan(source)

    years = {datetime.fromisoformat(c["taken"]).year for c in plan["carriers"]}
    assert years == set(YEARS) - {2020}


def test_without_a_pool_subject_the_album_keeps_its_old_rule(tmp_path):
    source = _bread_pool(tmp_path, pool_is_subject=False)

    plan = _no_model_plan(source)

    assert plan["carriers"] == []
    assert _story_selection(source)["stood_on_subject"] == []


def test_a_written_subject_on_a_date_range_is_not_a_curated_pool():
    window = (DateRange(datetime(2024, 3, 10), datetime(2024, 5, 20)),)

    intent = build_editorial_intent("custom", window, brief=SUBJECT)

    assert intent.subject == SUBJECT
    assert not intent.pool_is_subject


def test_a_pool_needs_the_subject_it_was_chosen_for():
    window = (DateRange(datetime(2024, 3, 10), datetime(2024, 5, 20)),)

    with pytest.raises(ValueError, match="written subject"):
        build_editorial_intent("album", window, brief="", pool_subject="  ")


def _pool_gate(kind: str, line: str, *, score: int) -> StandingGate:
    unit = {"asset_id": "clip", "kind": kind, "members": ["clip"]}
    gate = StandingGate(
        lambda _asset: score,
        line_of=lambda _asset: line,
        life=lambda _asset: False,
        unit_by_asset={"clip": ("E1", unit)},
        pictures_of={"K01": 7},
        context_without_life=True,
        pool_is_subject=True,
    )
    gate.ensure(["clip"])
    return gate


def test_a_pool_clip_scored_zero_stands_on_the_subject():
    gate = _pool_gate("video", "2022-01-01 | Dough being kneaded on a floured board.", score=0)

    assert gate.stands("clip", "minor", "K01")
    assert gate.stood_on_subject == {"clip"}


def test_a_pool_video_whose_frames_miss_the_subject_is_still_refused():
    line = "2022-01-01 | Dough on a floured board. | frames=subject_often_missing"

    gate = _pool_gate("video", line, score=0)

    assert not gate.stands("clip", "minor", "K01")
    assert not gate.stood_on_subject


class _Captured(RuntimeError):
    pass


def _captured_case(tmp_path, **pool):
    from unittest.mock import patch

    from immich_memories.analysis.editorial_people import adapt_editorial_people
    from immich_memories.analysis.editorial_runtime import EditorialRunContext
    from immich_memories.analysis.editorial_runtime_backend import ProductionPostCardBackend
    from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
    from immich_memories.analysis.selection_trace import Trace
    from immich_memories.config_loader import Config
    from tests.annotation_rows import annotation_store

    source = film_source(
        tmp_path,
        [Day(date(2021, 3, 14), "Baking")],
        seconds=20,
        span=(date(2021, 1, 1), date(2021, 12, 31)),
    )
    context = EditorialRunContext(
        "bread",
        "Bread",
        "album",
        (),
        60,
        tmp_path / "artifacts",
        album_ref="album-1",
        album_sources=tuple(source.assets.values()),
        **pool,
    )
    captured = {}

    def capture(_workprint, **kwargs):
        captured["case"] = kwargs["case"]
        raise _Captured

    backend = ProductionPostCardBackend(
        config=Config(),
        context=context,
        people=adapt_editorial_people({}),
        thumbnail_cache=object(),
        store=annotation_store(),
        bank_root=context.artifact_dir,
        ports=EditorialRuntimePorts(),
    )
    # WHY: capture_structure_input reads the library's evidence; intercepted to read its case arg
    with (
        # WHY: side_effect records the case the backend built, then stops before any evidence read
        patch(
            "immich_memories.analysis.editorial_runtime_backend.capture_structure_input",
            side_effect=capture,
        ),
        pytest.raises(_Captured),
    ):
        backend.edit(object(), trace=Trace())
    return captured["case"]


def test_an_album_handed_over_as_a_subject_pool_reaches_the_editor_as_one(tmp_path):
    case = _captured_case(tmp_path, base_brief=SUBJECT, pool_is_subject=True)

    assert case.pool_subject == SUBJECT


def test_an_album_with_no_pool_subject_reaches_the_editor_as_an_album(tmp_path):
    assert _captured_case(tmp_path).pool_subject is None


def test_a_subject_pool_is_only_an_album_with_its_written_subject(tmp_path):
    from immich_memories.analysis.editorial_runtime import EditorialRunContext

    window = (DateRange(datetime(2024, 3, 10), datetime(2024, 5, 20)),)
    with pytest.raises(ValueError, match="subject pool"):
        EditorialRunContext(
            "bread",
            "Bread",
            "custom",
            window,
            60,
            tmp_path,
            base_brief=SUBJECT,
            pool_is_subject=True,
        )


def test_a_captured_pool_must_carry_the_pool_contract(tmp_path):
    source = _bread_pool(tmp_path, pool_is_subject=True)

    with pytest.raises(ValueError, match="subject pool"):
        replace(source, intent=replace(source.intent, pool_is_subject=False))


def test_the_cli_hands_an_album_and_its_subject_over_as_a_subject_pool(tmp_path):
    from immich_memories.cli._editorial_context import build_editorial_context
    from immich_memories.cli._run_inputs import ResolvedRunInputs
    from immich_memories.config_loader import Config

    source = film_source(
        tmp_path,
        [Day(date(2021, 3, 14), "Baking")],
        seconds=20,
        span=(date(2021, 1, 1), date(2021, 12, 31)),
    )
    config = Config()
    resolved = ResolvedRunInputs.from_arguments(
        include_photos=True,
        photo_assets=list(source.assets.values()),
        dry_run=False,
        automation_attempt_id=None,
        upload_to_immich=False,
        config=config,
        person_names=[],
        music=None,
        memory_preset_params={"album_name": "Bread", "album_id": "album-1", "subject": SUBJECT},
    )

    context = build_editorial_context(
        resolved=resolved,
        config=config,
        memory_type="album",
        memory_key=None,
        output_stem="bread",
        assets=[],
        date_range=DateRange(datetime(2021, 3, 14), datetime(2021, 3, 15)),
        date_ranges=(),
        duration=60.0,
        transition="smart",
        title_override=None,
        person_names=[],
        accept_any_provenance=False,
    )

    assert context.pool_subject == SUBJECT


def _configured():
    from immich_memories.config_loader import Config

    config = Config()
    config.immich.url = "http://immich:2283"
    config.immich.api_key = "test-key"
    return config


def test_generate_hands_the_album_and_its_subject_to_the_album_route():
    from unittest.mock import MagicMock, patch

    from tests.test_cli_smoke import _invoke

    client = MagicMock()
    client.__enter__.return_value = client
    # WHY: the album route opens the Immich HTTP client before it dispatches.
    with (
        # WHY: SyncImmichClient is the Immich HTTP boundary; only the handoff is checked.
        patch("immich_memories.api.immich.SyncImmichClient", return_value=client),
        # WHY: album generation reads the album from Immich and renders it.
        patch("immich_memories.cli._album_generation.handle_album_generation") as album_route,
    ):
        result = _invoke(
            ["generate", "--from-album", "Bread", "--subject", SUBJECT, "--dry-run"], _configured()
        )

    assert result.exit_code == 0, result.output
    assert album_route.call_args.kwargs["subject"] == SUBJECT


def test_a_subject_without_an_album_is_refused():
    from tests.test_cli_smoke import _invoke

    result = _invoke(["generate", "--year", "2024", "--subject", SUBJECT], _configured())

    assert result.exit_code != 0
    assert "--from-album" in result.output


def test_a_pool_year_the_reader_weighed_as_nothing_still_gets_its_shot(tmp_path):
    from tests.editorial_film_fixtures import FilmJudge
    from tests.test_editorial_duration_planner_integration import run

    source = _bread_pool(tmp_path, pool_is_subject=True)

    # WHY: the judge stands in for the model reader, which weighed every baking day as nothing.
    plan = run(source, FilmJudge(weigh=lambda _row: "none"))

    years = {datetime.fromisoformat(c["taken"]).year for c in plan["carriers"]}
    assert years == set(YEARS)
