"""The web brief is generate's flags, one to one, and the page can show the command it runs."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from immich_memories.web.brief import CutBrief


def test_a_brief_becomes_the_generate_command_it_stands_for():
    brief = CutBrief(
        memory_type="person_spotlight",
        year=2024,
        person=["Ana", "Luc"],
        person_match="or",
        duration=90,
        include_photos=True,
        include_live_photos=False,
        sharing="family",
    )

    argv = brief.argv(
        executable="immich-memories", config=Path("/c.yaml"), output=Path("/o/web-1.mp4")
    )

    assert argv[:4] == ["immich-memories", "--config", "/c.yaml", "generate"]
    assert "--memory-type=person_spotlight" in argv
    assert "--year=2024" in argv
    assert argv.count("--person=Ana") == 1 and "--person=Luc" in argv
    assert "--person-match=or" in argv
    assert "--duration=90" in argv
    assert "--include-photos" in argv and "--no-live-photos" in argv
    assert "--sharing=family" in argv
    assert argv[-3:] == ["--no-render", "--output", "/o/web-1.mp4"]


def test_the_shown_command_is_one_a_person_can_run_and_hides_the_server_s_own_flags():
    brief = CutBrief(memory_type="on_this_day", day=date(2024, 6, 1), person=["-rf /"])

    shown = brief.shown_command()

    assert shown.startswith("immich-memories generate ")
    assert "--config" not in shown and "--output" not in shown
    # A value is always one argument: a name that starts with a dash is not a flag.
    assert "'--person=-rf /'" in shown
    assert "--day=2024-06-01" in shown and shown.endswith("--no-render")


def test_every_flag_a_brief_can_emit_is_one_generate_accepts():
    from immich_memories.cli import main

    generate = main.commands["generate"]
    accepted = {name for param in generate.params for name in (*param.opts, *param.secondary_opts)}
    everything = CutBrief(
        memory_type="trip",
        year=2024,
        month=6,
        start=date(2024, 6, 1),
        end=date(2024, 6, 30),
        period="1m",
        season="summer",
        hemisphere="south",
        holiday="christmas",
        birthday="auto",
        person=["Ana"],
        people_expression="Ana",
        person_match="and",
        from_album="Trip",
        day=date(2024, 6, 1),
        trip_index=1,
        all_trips=True,
        years_back=2,
        near_date=date(2024, 6, 1),
        event_id="e1",
        duration=60,
        include_photos=False,
        include_live_photos=True,
        sharing="shareable",
        include_asset=["a"],
        exclude_asset=["b"],
        ask="our cat",
    )

    emitted = {flag.split("=")[0] for flag in everything._flags()}

    assert emitted <= accepted, emitted - accepted


def test_a_season_brief_leaves_its_length_to_the_cli_s_date_range_curve():
    """The web and the CLI give a season the same length (#1503): the brief sends none."""
    brief = CutBrief(memory_type="season", year=2024, season="summer")

    argv = brief.argv(
        executable="immich-memories", config=Path("/c.yaml"), output=Path("/o/web-1.mp4")
    )

    assert "--memory-type=season" in argv and "--season=summer" in argv
    assert not any(arg.startswith("--duration") for arg in argv)


def test_a_sentence_is_the_whole_brief_and_travels_as_one_argument():
    brief = CutBrief(ask="--year=2020 our cat along the years")

    argv = brief.argv(executable="immich-memories", config=None, output=Path("/o/web-1.mp4"))

    assert "--ask=--year=2020 our cat along the years" in argv
    assert not any(arg.startswith("--year") for arg in argv)
    assert brief.shown_command() == (
        "immich-memories generate '--ask=--year=2020 our cat along the years' --no-render"
    )
