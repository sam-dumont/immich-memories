"""Progress headings travel as a stage key and params, and every reader words them (#1960)."""

from __future__ import annotations

import re
from pathlib import Path
from string import Formatter

import pytest
from babel.messages.pofile import read_po

from immich_memories.i18n import LOCALES_DIR, SUPPORTED_LOCALES
from immich_memories.operations.cut_progress import StageUpdate
from immich_memories.progress_text import (
    FRAMED,
    STAGE_TEXTS,
    Stage,
    catalogue_key,
    coded,
    coded_pass,
    current_span_name,
    heading,
    stage_text,
    words,
)

REPO = Path(__file__).resolve().parents[1]
STAGES_TS = REPO / "web/src/lib/stages.ts"


def _client_stages() -> dict[str, str]:
    """The client's `STAGES` table, key -> msgid, read from its source."""
    source = STAGES_TS.read_text()
    body = source.split("const STAGES", 1)[1].split("\n};", 1)[0]
    entries = re.findall(r"^\s*'?([a-z_.]+)'?: N_\('((?:\\.|[^'])*)'\),$", body, re.M)
    return {key: text.replace("\\'", "'") for key, text in entries}


def _fields(template: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(template) if field is not None}


def test_every_stage_the_backend_announces_has_a_template():
    assert {stage.value for stage in Stage} <= set(STAGE_TEXTS)


def test_the_client_words_exactly_the_keys_the_server_sends():
    # WHY: no boundary; reads the client's source. The two tables are kept by hand, one
    # for the browser and one for the terminal, and must never drift.
    assert _client_stages() == STAGE_TEXTS
    assert f"t('{FRAMED}'" in STAGES_TS.read_text()


@pytest.mark.parametrize("locale", [code for code in SUPPORTED_LOCALES if code != "en"])
def test_every_heading_is_translated_with_its_placeholders(locale: str):
    path = LOCALES_DIR / locale.replace("-", "_") / "LC_MESSAGES/ui.po"
    with path.open("rb") as handle:
        catalogue = read_po(handle, locale=locale.replace("-", "_"))
    for template in {*STAGE_TEXTS.values(), FRAMED}:
        entry = catalogue.get(template)
        assert entry is not None and entry.string, (locale, template)
        assert _fields(str(entry.string)) == _fields(template), (locale, template)


def test_every_stage_update_in_the_source_is_announced_by_key():
    # WHY: no boundary; reads the source. A literal first argument is an English sentence
    # the web client could only show in English.
    literal = re.compile(r"StageUpdate\(\s*f?[\"']")
    offenders = [
        f"{path.relative_to(REPO)}:{source[: match.start()].count(chr(10)) + 1}"
        for path in sorted((REPO / "src/immich_memories").rglob("*.py"))
        for source in [path.read_text()]
        for match in literal.finditer(source)
    ]
    assert not offenders, offenders


def test_a_coded_heading_words_in_english_and_in_french():
    card = coded(Stage.RENDER_YEAR_CARD, index=2, count=9)

    assert stage_text(card) == "Year divider 2 of 9"
    assert stage_text(card, "fr") == "Intertitre d’année 2 sur 9"
    assert heading(card) == ("render.year_card", {"index": "2", "count": "9"})


def test_a_counted_card_frame_says_so_after_its_heading():
    frame = coded(Stage.RENDER_LOCATION_CARD, index=1, count=3, frame=10, frames=20)

    assert stage_text(frame) == "Location card 1 of 3 (frame 10/20)"
    assert stage_text(frame, "fr") == "Carte de lieu 1 sur 3 (image 10/20)"


def test_a_value_with_reserved_characters_survives_the_trip():
    name = "IMG 0001 & co?.HEIC"

    assert stage_text(coded(Stage.RENDER_DOWNLOADING, name=name)) == f"Downloading: {name}"


def test_text_that_is_not_coded_is_left_as_it_is():
    assert stage_text("Generating title screen...") == "Generating title screen..."
    assert stage_text("stage.not_a_key?x=1") == "stage.not_a_key?x=1"
    assert heading("Encoding video...") == ("", {})


def test_a_wait_reads_as_a_duration_in_the_terminal():
    unprepared = coded(Stage.ASK_UNPREPARED, count=120, duration_seconds=600, duration="10 min")

    assert stage_text(unprepared) == (
        "120 pictures in this period aren't prepared yet; preparing them first takes about 10 min"
    )


def test_every_pass_name_has_a_heading_even_one_the_table_has_not_met():
    assert catalogue_key("videos.detectors") == "videos.detectors"
    assert catalogue_key("videos.new_pass") == "videos.other"
    assert catalogue_key("live_photos.new_pass") == "live_photos.other"
    assert catalogue_key("brand_new") == "pictures.other"
    assert catalogue_key("Reading event evidence") == ""
    assert heading(coded_pass("videos.new_pass", done=3, total=9)) == (
        "videos.other",
        {"done": "3", "total": "9"},
    )


def test_a_keyed_stage_reads_in_english_with_its_counts():
    update = StageUpdate(Stage.CUT_FAMILY_CHECK, done=3, total=10)

    assert update.stage_label == "Running the family-viewing check: 3/10"
    assert update.catalogue_key == "cut.family_check"
    # A preparation pass keeps the terminal line it always had.
    assert StageUpdate("previews", "analysis", 1, 6).stage_label == "Preparing previews: 1/6"


def test_a_change_of_params_is_a_new_position():
    """The attempt skips an update identical to the last one: a new month must not be one."""
    march = StageUpdate(Stage.CUT_PERIOD_ACCOUNT, params={"month": "2024-03"})
    april = StageUpdate(Stage.CUT_PERIOD_ACCOUNT, params={"month": "2024-04"})

    assert march.identity != april.identity
    assert march.stage_key == april.stage_key == "cut.period_account"
    restored = StageUpdate.from_record(april.as_record())
    assert restored is not None and restored.params == {"month": "2024-04"}
    assert restored.stage_label == "Reading the period account: 2024-04"


def test_words_fill_the_french_template_from_the_shared_catalogue():
    assert words("cut.period_account", {"month": "2024-03"}, "fr") == (
        "Lecture du récit de la période : 2024-03"
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("stage.analysis.Preparing editorial evidence", "stage.analysis.cut.evidence"),
        ("stage.selection.event evidence", "stage.selection.cut.event_packs"),
        ("stage.selection.Reading the period account", "stage.selection.cut.period_account"),
        ("stage.selection.waiting on openai batch", "stage.selection.cut.batch_waiting"),
        ("stage.analysis.previews", "stage.analysis.previews"),
        ("render.assembly", "render.assembly"),
    ],
)
def test_history_from_before_keys_still_estimates_the_next_run(before: str, after: str):
    assert current_span_name(before) == after


def test_a_run_measured_before_keys_still_estimates_a_keyed_stage():
    """Without the rename, the keyed stage is unknown to the plan, which then drops it."""
    from dataclasses import replace

    from immich_memories.operations.cut_progress import StageClock
    from immich_memories.tracking.span_progress import SpanPlan
    from immich_memories.tracking.timing import Span, collecting

    measured = [
        Span(1, "stage.analysis.Preparing editorial evidence", None, 0, 10),
        Span(2, "stage.selection.Reading the period account", None, 10, 30),
    ]
    plan = SpanPlan([replace(span, name=current_span_name(span.name)) for span in measured])
    with collecting(now=lambda: 0.0):
        update = StageClock(plan=plan).measure(
            StageUpdate(Stage.CUT_PERIOD_ACCOUNT, params={"month": "2024-03"})
        )

    assert update.total_fraction is not None
