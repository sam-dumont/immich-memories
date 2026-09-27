"""`people scan`, `show`, `export` and `import` — the graph from a terminal.

The library answered here is invented; the point of the assertions is the
shape of the output, not who is in it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from immich_memories.db import open_store
from immich_memories.people.companion import add_confirmed_person, load_document, people_entries


@dataclass
class _Person:
    id: str
    name: str
    birth_date: date | None = None


@dataclass
class _Bucket:
    time_bucket: str
    count: int


@dataclass
class _Account:
    name: str


class _Library:
    """An Immich holding one household and one person met at a race."""

    people = [
        _Person("p1", "Alex Example"),
        _Person("p2", "Sam Sample"),
        _Person("p3", "Rowan Example"),
    ]
    months = {
        "p1": [(date(2010 + m // 12, m % 12 + 1, 1), 20) for m in range(190)],
        "p2": [(date(2018 + (5 + m) // 12, (5 + m) % 12 + 1, 1), 20) for m in range(90)],
        "p3": [(date(2021, 5, 1), 80), (date(2023, 5, 1), 80)],
    }
    days = {
        None: {date(2020, 4, day): 5 for day in range(1, 11)},
        "p1": {date(2020, 4, 2): 2, date(2020, 4, 5): 1, date(2020, 4, 9): 1},
    }

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self) -> _Library:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get_all_people(self, with_hidden: bool = False) -> list[_Person]:
        return self.people

    def get_time_buckets(self, **kwargs: object) -> list[_Bucket]:
        if kwargs.get("size") == "DAY":
            return [
                _Bucket(f"{day:%Y-%m-%d}T00:00:00.000Z", count)
                for day, count in self.days.get(kwargs.get("person_id"), {}).items()
            ]
        return [
            _Bucket(f"{month:%Y-%m-%d}T00:00:00.000Z", count)
            for month, count in self.months[str(kwargs["person_id"])]
        ]

    def count_assets_with_people(self, person_ids: list[str]) -> int:
        return 0

    def get_current_user(self) -> _Account:
        return _Account("Alex Example")


def _unwrapped(text: str) -> str:
    """Rich wraps a long path to the terminal width; the path is still there."""
    return "".join(text.split())


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path: Path) -> Path:
    # A scan writes its measurements under ~/.immich-memories; never the developer's.
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _run(args: list[str], client: object | None = None, *, exit_code: int = 0) -> str:
    from immich_memories.cli import main
    from immich_memories.config_loader import Config

    config = Config()
    config.immich.url = "https://immich.example.com"
    config.immich.api_key = "not-a-real-key"

    # WHY: the CLI group loads the user's real config directory on startup, and
    # the scan would otherwise talk to whatever Immich this machine points at.
    # WHY: replaces config init, config load, and the Immich client the CLI opens.
    with (
        # WHY: init_config_dir would create a real config directory in the user's home.
        patch("immich_memories.cli.init_config_dir"),
        # WHY: get_config would read the developer's own config.yaml off disk.
        patch("immich_memories.cli.get_config", return_value=config),
        # WHY: SyncImmichClient is the Immich boundary; this swaps in the in-memory client.
        patch("immich_memories.api.sync_client.SyncImmichClient", client or _Library),
    ):
        result = CliRunner().invoke(main, args, catch_exceptions=False)
    assert result.exit_code == exit_code, result.output
    return result.output


class TestScan:
    def test_it_writes_the_people_registry_to_the_store_and_says_so(self):
        output = _run(["people", "scan"])

        assert "people in the store" in output
        assert len(people_entries(load_document())) == 3

    def test_it_writes_the_refreshable_evidence_graph_as_a_file(self, tmp_path):
        output = _run(["people", "scan"])

        graph_path = tmp_path / ".immich-memories" / "people-graph.json"
        graph = json.loads(graph_path.read_text())
        assert _unwrapped(str(graph_path)) in _unwrapped(output)
        assert len(graph["nodes"]) == 3
        assert graph["edges"] == []

    def test_it_refreshes_a_confirmed_immich_face_below_the_normal_floor(self):
        class LibraryWithUncle(_Library):
            people = [*_Library.people, _Person("p4", "Taylor Sample")]
            months = {**_Library.months, "p4": [(date(2020, 1, 1), 8)]}

        add_confirmed_person(open_store(), "Taylor Sample", person_id="p4", role="uncle")

        _run(["people", "scan"], LibraryWithUncle)

        taylor = next(entry for entry in people_entries(load_document()) if "p4" in entry["ids"])
        assert taylor["inferred"]["evidence"]["count"] == 8
        assert taylor["confirmed"]["role"] == "uncle"

    def test_it_reports_the_tiers_without_reading_out_the_roster(self):
        output = _run(["people", "scan"])

        assert "inner" in output and "event" in output
        assert "Rowan Example" not in output

    def test_it_says_how_it_worked_out_who_the_owner_is(self):
        output = _run(["people", "scan"])

        assert "account" in output

    def test_being_told_the_owner_puts_that_name_in_the_registry(self):
        _run(["people", "scan", "--owner", "Sam Sample"])

        assert load_document()["owner"]["name"] == "Sam Sample"


class TestTheBareCommand:
    def test_it_still_lists_the_people_immich_knows(self):
        # `immich-memories people` predates the graph and is documented as the
        # way to find the exact name `--person` matches on. Growing subcommands
        # underneath it must not take that away.
        output = _run(["people"], _Library)

        assert "Rowan Example" in output
        assert "3 named people" in output


class TestShow:
    def test_it_reads_what_a_scan_left_behind(self):
        _run(["people", "scan"])

        output = _run(["people", "show"])

        assert "Alex Example" in output
        assert "inner" in output

    def test_it_says_so_when_no_scan_has_run(self):
        output = _run(["people", "show"])

        assert "people scan" in output

    def test_that_sentence_survives_a_narrow_terminal(self, monkeypatch):
        # The same sentence, read from a 40-column window: what the CLI prints
        # is not allowed to depend on the terminal the suite happens to run in.
        monkeypatch.setenv("COLUMNS", "40")

        output = _run(["people", "show"])

        assert "people scan" in output

    def test_show_carries_the_era_day_share(self):
        _run(["people", "scan"])

        output = _run(["people", "show"])

        assert "covid 30%" in output

    def test_one_tier_can_be_asked_for_on_its_own(self):
        _run(["people", "scan"])

        output = _run(["people", "show", "--tier", "event"])

        assert "Rowan Example" in output
        assert "Sam Sample" not in output


class TestExportAndImport:
    def test_an_export_is_a_file_only_its_owner_can_read(self, tmp_path):
        _run(["people", "scan"])
        target = tmp_path / "people.yaml"

        _run(["people", "export", "--to", str(target)])

        assert target.stat().st_mode & 0o077 == 0
        assert len(yaml.safe_load(target.read_text())["people"]) == 3

    def test_an_export_without_a_target_goes_to_standard_output(self):
        _run(["people", "scan"])

        output = _run(["people", "export"])

        assert "Rowan Example" in output

    def test_an_edited_export_comes_back_with_its_ids_and_answers(self, tmp_path):
        _run(["people", "scan"])
        target = tmp_path / "people.yaml"
        _run(["people", "export", "--to", str(target)])
        document = yaml.safe_load(target.read_text())
        document["people"][0]["confirmed"]["role"] = "partner"
        target.write_text(yaml.dump(document, sort_keys=False))

        output = _run(["people", "import", "--from", str(target)])

        assert "3 people imported" in output
        assert load_document() == document

    def test_a_broken_file_is_refused_and_changes_nothing(self, tmp_path):
        _run(["people", "scan"])
        before = load_document()
        target = tmp_path / "people.yaml"
        target.write_text("version: 1\npeople:\n  - ids: p1\n    name: Typo\n")

        output = _run(["people", "import", "--from", str(target)], exit_code=1)

        assert "nothing changed" in output
        assert "people[0]" in output
        assert load_document() == before
