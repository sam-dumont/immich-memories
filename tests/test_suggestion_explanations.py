"""Discovery explains an empty library without exposing internal candidate keys."""

from datetime import date
from unittest.mock import create_autospec

import pytest
from rich.console import Console

from immich_memories.api.accounts import OpenAccount
from immich_memories.api.compatibility import ResolvedApiVersion
from immich_memories.api.immich import SyncImmichClient
from immich_memories.api.models import UserInfo
from immich_memories.automation import candidate_discovery
from immich_memories.automation.calendar_detectors import MonthlyDetector
from immich_memories.automation.candidate_discovery import CandidateDiscovery
from immich_memories.automation.candidates import make_memory_key
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.cli import auto_cmd
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.tracking import RunDatabase


@pytest.mark.parametrize("enabled", [True, False])
def test_every_enabled_detector_explains_an_empty_library(monkeypatch, enabled):
    flags = (
        "detect_monthly",
        "detect_yearly",
        "detect_trips",
        "detect_person_spotlight",
        "detect_activity_burst",
        "detect_groups",
        "detect_seasons",
        "detect_holidays",
        "detect_albums",
        "detect_person_monthly",
        "backfill_months",
    )
    config = Config(
        immich={"url": "https://immich.example.test", "api_key": "key"},
        automation=dict.fromkeys(flags, enabled),
    )
    # WHY: the remote Immich account supplies a valid but empty library.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_time_buckets.return_value = []
    client.get_all_people.return_value = []
    client.get_albums.return_value = []
    account = OpenAccount(
        "primary", client, UserInfo(id="owner", email="owner@example.test"), ResolvedApiVersion.V3
    )
    monkeypatch.setattr(candidate_discovery, "open_accounts", lambda *_args: {"primary": account})
    # WHY: country lookup normally calls the remote geodata service.
    monkeypatch.setattr(candidate_discovery, "known_home_country", lambda _config: None)
    store = open_store(config)
    found = CandidateDiscovery(config, RunDatabase(store), AutomationStateStore(store)).discover(
        limit=10, recent_auto_runs=[]
    )

    assert found.candidates == []
    for kind in (
        "month",
        "year",
        "person spotlight",
        "people together",
        "busy month",
        "on this day",
        "birthday",
        "trip",
        "special day",
        "group",
        "season",
        "holiday",
        "album",
        "person month",
        "missed month",
    ):
        expected = enabled or kind in {"on this day", "birthday", "special day"}
        assert any(note.startswith(f"No {kind} film:") for note in found.notes) == expected, (
            kind,
            found.notes,
        )


def test_a_filmed_month_explains_why_it_is_absent():
    notes = []
    key = make_memory_key("monthly_highlights", date(2030, 5, 1), date(2030, 5, 31))
    found = MonthlyDetector().detect(
        {"2030-05": 80}, [], {key}, Config(), date(2030, 6, 10), notes=notes
    )
    assert found == []
    assert notes == ["No month film: the last completed month already has a film"]


def test_the_terminal_uses_readable_types_without_a_duplicate_category(monkeypatch):
    found = MonthlyDetector().detect({"2030-05": 80}, [], set(), Config(), date(2030, 6, 10))
    output = Console(width=80, record=True)
    # WHY: capture the actual terminal rendering at a normal terminal width.
    monkeypatch.setattr(auto_cmd, "console", output)
    auto_cmd._print_candidates_table(found)
    rendered = output.export_text()
    assert "Monthly Highlights" in rendered
    assert "monthly_highlights" not in rendered
    assert "monthly_review" not in rendered
    assert "Category" not in rendered


def test_cli_and_web_show_the_same_default_candidates_and_notes(monkeypatch, tmp_path):
    import json
    from dataclasses import replace

    from click.testing import CliRunner

    from immich_memories.automation.runner import AutoRunner
    from immich_memories.automation.status import SuggestStatus
    from immich_memories.automation.variety import VarietyDecision
    from tests.test_web_suggestions import _client

    template = MonthlyDetector().detect({"2030-05": 80}, [], set(), Config(), date(2030, 6, 10))[0]
    candidates = [replace(template, memory_key=f"candidate-{i}") for i in range(15)]
    # WHY: discovery normally reads Immich; both presentation surfaces get one fixed result.
    runner = create_autospec(AutoRunner, instance=True)
    runner.suggest.side_effect = lambda limit: candidates[:limit]
    runner.last_notes = ("No album film: albums already have hand-made films",)
    runner.last_variety_decision = VarietyDecision(eligible=candidates, rejected=[])
    runner.last_backoff_skips = {}
    runner.last_suggest_status = SuggestStatus()
    monkeypatch.setattr(
        "immich_memories.automation.runner.AutoRunner", lambda *_args, **_kwargs: runner
    )
    cli = CliRunner()
    obj = {"config": Config(), "config_path": None}
    printed = cli.invoke(auto_cmd.auto, ["suggest", "--json"], obj=obj)
    assert printed.exit_code == 0, printed.output
    body = _client(tmp_path, runner).get("/api/v1/suggestions").json()
    assert [row["memory_key"] for row in json.loads(printed.output)] == [
        row["memory_key"] for row in body["candidates"]
    ]
    assert len(body["candidates"]) == 10
    assert body["notes"] == list(runner.last_notes)
    human = cli.invoke(auto_cmd.auto, ["suggest"], obj=obj)
    assert human.exit_code == 0
    assert runner.last_notes[0] in human.output


def test_human_backoff_labels_omit_internal_identifiers(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from immich_memories.automation.runner import AutoRunner
    from immich_memories.automation.status import SuggestStatus
    from immich_memories.automation.variety import VarietyDecision
    from tests.test_web_suggestions import _client

    # WHY: failed-attempt history comes from discovery, not presentation.
    runner = create_autospec(AutoRunner, instance=True)
    runner.suggest.return_value = []
    runner.last_notes = ()
    runner.last_suggest_status = SuggestStatus()
    runner.last_variety_decision = VarietyDecision(eligible=[], rejected=[])
    runner.last_backoff_skips = {
        "album:2030-05-01:2030-05-05::internal-album-id:42": "failed twice"
    }
    monkeypatch.setattr(
        "immich_memories.automation.runner.AutoRunner", lambda *_args, **_kwargs: runner
    )
    printed = CliRunner().invoke(
        auto_cmd.auto, ["suggest"], obj={"config": Config(), "config_path": None}
    )
    body = _client(tmp_path, runner).get("/api/v1/suggestions").json()
    assert printed.exit_code == 0
    assert "internal-album-id" not in printed.output
    assert "internal-album-id" not in str(body["skipped"])
    assert "Album" in printed.output and "2030-05-01" in printed.output
    assert body["skipped"] == [{"label": "Album: 2030-05-01 to 2030-05-05", "rule": "failed twice"}]


def test_person_month_does_not_call_an_empty_older_month_already_filmed():
    from immich_memories.api.models import Person
    from immich_memories.automation.candidates import make_manual_memory_key
    from immich_memories.automation.person_detectors import PersonMonthlyDetector

    key = make_manual_memory_key(
        "monthly_highlights", date(2030, 5, 1), date(2030, 5, 31), ["Subject"]
    )
    found = PersonMonthlyDetector().detect(
        [Person(id="subject", name="Subject")], {"subject"}, {}, {key}, date(2030, 6, 10)
    )
    assert found.candidates == []
    assert len(found.notes) == 1
    assert "15 pictures over 4 days" in found.notes[0]
    assert "already have films" not in found.notes[0]
