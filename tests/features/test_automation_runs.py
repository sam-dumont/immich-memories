"""Feature tests: what `auto run`, the HTTP trigger and the daily timer do with a library.

Each runs the real decision (discovery, rotation rules, cooldown, attempt history) against
a picture-level Immich (tests/features/automation_library.py). The `generate` child is the
one stand-in: it records the film it was asked for in the store, as the real child does;
the films those children really render and deliver are in
tests/integration/features/test_automation_delivery.py.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from immich_memories.automation.models import AutoOutcome
from tests.auto_library_fake import FakeGenerateChild, last_month
from tests.features.automation_library import (
    Library,
    LocalHttp,
    cli,
    immich_holding,
    record_film,
    suggest_text,
    write_config,
)

# A fresh strong token per run: the server refuses weak ones, and no literal sits in the source.
TOKEN = secrets.token_hex(32)


class _FailingChild(FakeGenerateChild):
    """A `generate` child that exits 1 without a film, as a broken render does."""

    def __call__(self, cmd: list[str]) -> Any:
        from immich_memories.automation.models import ProcessResult

        self.commands.append(cmd)
        return ProcessResult(returncode=1, stdout="", stderr="render failed: no frames")


@pytest.fixture
def child(tmp_path: Path) -> Iterator[FakeGenerateChild]:
    recorder = FakeGenerateChild(tmp_path / "films")
    # WHY: the `generate` child process; the stand-in records the film it was asked for.
    with patch("immich_memories.automation.runner._execute_generate", recorder):
        yield recorder


@pytest.fixture
def failing_child(tmp_path: Path) -> Iterator[_FailingChild]:
    recorder = _FailingChild(tmp_path / "films")
    # WHY: the `generate` child process; this one fails every render.
    with patch("immich_memories.automation.runner._execute_generate", recorder):
        yield recorder


def _two_candidates() -> Library:
    """Last month (a monthly film) and a year two years back (a year film)."""
    start, _ = last_month()
    old = date.today().year - 2
    return Library().month(f"{start:%Y-%m}", 80).month(f"{old}-05", 60).month(f"{old}-09", 60)


def _auto_run(config: Path, library: Library, *flags: str) -> dict[str, Any]:
    """`auto run --quiet <flags>`: the one JSON line a wrapper reads."""
    with immich_holding(library):
        result = cli(config, "auto", "run", "--quiet", *flags)
    return json.loads(result.stdout.strip().splitlines()[-1])


def _suggested_keys(config: Path, library: Library) -> list[str]:
    with immich_holding(library):
        result = cli(config, "auto", "suggest", "--json")
    assert result.exit_code == 0, result.output
    return [row["memory_key"] for row in json.loads(result.stdout)]


def _asked_for(child: FakeGenerateChild) -> list[str]:
    """The memory key each `generate` child was asked to make."""
    return [
        arg.split("=", 1)[1]
        for command in child.commands
        for arg in command
        if arg.startswith("--memory-key=")
    ]


# ── auto run ─────────────────────────────────────────────────────────────


@pytest.mark.feature("automation.run")
def test_auto_run_makes_the_best_candidate(tmp_path: Path, child: FakeGenerateChild) -> None:
    config = write_config(tmp_path)
    best = _suggested_keys(config, _two_candidates())[0]

    result = _auto_run(config, _two_candidates())

    assert result["outcome"] == "completed", result
    assert result["candidate_key"] == best
    assert _asked_for(child) == [best]


@pytest.mark.feature("automation.run")
def test_auto_run_makes_the_chosen_candidate(tmp_path: Path, child: FakeGenerateChild) -> None:
    config = write_config(tmp_path)
    second = _suggested_keys(config, _two_candidates())[1]

    result = _auto_run(config, _two_candidates(), "--candidate", second)

    assert result["outcome"] == "completed", result
    assert _asked_for(child) == [second]


@pytest.mark.feature("automation.run")
def test_a_second_run_the_same_day_makes_nothing(tmp_path: Path, child: FakeGenerateChild) -> None:
    config = write_config(tmp_path)
    _auto_run(config, _two_candidates())

    again = _auto_run(config, _two_candidates())

    assert again["outcome"] == "skipped"
    assert again["reason"] == "cooldown active"
    assert len(child.commands) == 1


@pytest.mark.feature("automation.run")
def test_nothing_worth_a_film_makes_nothing(tmp_path: Path, child: FakeGenerateChild) -> None:
    result = _auto_run(write_config(tmp_path), Library())

    assert result["outcome"] == "skipped"
    assert result["reason"] == "no eligible candidates"
    assert child.commands == []


# ── --dry-run ────────────────────────────────────────────────────────────


@pytest.mark.feature("automation.run-dry-run")
def test_a_dry_run_names_the_decision_and_makes_no_film(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path)
    best = _suggested_keys(config, _two_candidates())[0]

    result = _auto_run(config, _two_candidates(), "--dry-run")

    assert result["outcome"] == "dry_run"
    assert result["candidate_key"] == best
    assert child.commands == []
    assert not list((tmp_path / "films").glob("*.mp4"))


@pytest.mark.feature("automation.run-dry-run")
def test_the_daily_timer_still_makes_the_film_after_a_dry_run(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    from immich_memories.automation.in_process_scheduler import InProcessScheduler
    from immich_memories.config.loader import load_config

    config = write_config(tmp_path, automation={"enabled": True, "daily_at": "09:00"})
    _auto_run(config, _two_candidates(), "--dry-run")
    loaded = load_config(config)
    at_ten = datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)
    timer = InProcessScheduler(lambda: loaded, clock=lambda: at_ten)

    with immich_holding(_two_candidates()):
        fired = asyncio.run(timer.tick())

    assert fired
    assert timer.snapshot().last_outcome == "completed"
    assert len(child.commands) == 1


# ── --force, --cooldown, --upload ────────────────────────────────────────


@pytest.mark.feature("automation.run-overrides")
def test_force_makes_a_film_inside_the_cooldown(tmp_path: Path, child: FakeGenerateChild) -> None:
    config = write_config(tmp_path)
    first = _auto_run(config, _two_candidates())

    forced = _auto_run(config, _two_candidates(), "--force")

    assert forced["outcome"] == "completed", forced
    assert forced["candidate_key"] != first["candidate_key"]
    assert len(child.commands) == 2


def _an_auto_film_hours_ago(config: Path, hours: float) -> None:
    old = date.today().year - 5
    record_film(
        config,
        "year_in_review",
        f"year_in_review:{old}-01-01:{old}-12-31:",
        source="auto",
        category="year_in_review",
        hours_ago=hours,
    )


@pytest.mark.feature("automation.run-overrides")
def test_cooldown_sets_the_wait_for_this_run(tmp_path: Path, child: FakeGenerateChild) -> None:
    config = write_config(tmp_path)
    _an_auto_film_hours_ago(config, 3)

    waiting = _auto_run(config, _two_candidates())
    shorter = _auto_run(config, _two_candidates(), "--cooldown", "2")

    assert waiting["reason"] == "cooldown active"
    assert shorter["outcome"] == "completed", shorter
    assert len(child.commands) == 1


@pytest.mark.feature("automation.run-overrides")
def test_a_cooldown_longer_than_the_gap_still_waits(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path)
    _an_auto_film_hours_ago(config, 3)

    result = _auto_run(config, _two_candidates(), "--cooldown", "4")

    assert result["reason"] == "cooldown active"
    assert child.commands == []


@pytest.mark.feature("automation.run-overrides")
def test_upload_asks_the_child_to_deliver_the_film(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path)

    _auto_run(config, _two_candidates())
    _auto_run(config, _two_candidates(), "--force", "--upload")

    assert "--upload-to-immich" not in child.commands[0]
    assert "--upload-to-immich" in child.commands[1]


# ── delivery settings ────────────────────────────────────────────────────


def _album_flag(command: list[str]) -> str | None:
    return command[command.index("--album") + 1] if "--album" in command else None


@pytest.mark.feature("automation.upload")
def test_the_old_automation_switch_and_album_still_deliver_automatic_films(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(
        tmp_path, automation={"upload_to_immich": True, "album_name": "Automatic films"}
    )

    _auto_run(config, _two_candidates())

    assert "--upload-to-immich" in child.commands[0]
    assert _album_flag(child.commands[0]) == "Automatic films"


@pytest.mark.feature("automation.upload")
def test_upload_set_by_itself_wins_over_the_old_automation_pair(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(
        tmp_path,
        automation={"upload_to_immich": True, "album_name": "Automatic films"},
        upload={"enabled": True, "album_name": "Memories"},
    )

    _auto_run(config, _two_candidates())

    assert "--upload-to-immich" in child.commands[0]
    assert _album_flag(child.commands[0]) == "Memories"


@pytest.mark.feature("automation.upload")
def test_without_an_automation_album_films_go_to_the_upload_album(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path, upload={"enabled": True, "album_name": "Memories"})

    _auto_run(config, _two_candidates())

    assert "--upload-to-immich" in child.commands[0]
    assert _album_flag(child.commands[0]) == "Memories"


@pytest.mark.feature("automation.upload")
def test_with_both_switches_off_films_stay_on_disk(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path, automation={"album_name": "Automatic films"})

    _auto_run(config, _two_candidates())

    assert "--upload-to-immich" not in child.commands[0]
    assert _album_flag(child.commands[0]) is None


# ── hand-made films ──────────────────────────────────────────────────────


@pytest.mark.feature("automation.hand-made-counts")
def test_a_hand_made_month_is_not_proposed_again(tmp_path: Path) -> None:
    from immich_memories.automation.candidates import make_manual_memory_key

    config = write_config(tmp_path)
    start, end = last_month()
    library = Library().month(f"{start:%Y-%m}", 80)
    before = _suggested_keys(config, library)
    # The key `generate --memory-type monthly_highlights` records for that month.
    record_film(
        config, "monthly_highlights", make_manual_memory_key("monthly_highlights", start, end)
    )

    after = _suggested_keys(config, library)

    assert f"monthly_highlights:{start}:{end}:" in before
    assert after == []


# ── rotation rules ───────────────────────────────────────────────────────


def _only_last_month() -> Library:
    start, _ = last_month()
    return Library().month(f"{start:%Y-%m}", 80)


@pytest.mark.feature("automation.rotation-rules")
def test_the_previous_category_cannot_repeat_and_the_day_is_skipped(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path)
    old = date.today().year - 5
    record_film(
        config,
        "monthly_highlights",
        f"monthly_highlights:{old}-03-01:{old}-03-31:",
        source="auto",
        category="monthly_review",
        hours_ago=48,
    )

    result = _auto_run(config, _only_last_month())
    forced = _auto_run(config, _only_last_month(), "--force")

    assert result["outcome"] == "skipped"
    assert result["reason"] == "no eligible candidates"
    assert [r["rule"] for r in result["rejections"]] == ["same_category_as_previous"]
    # --force skips the cooldown, never a rule.
    assert forced["outcome"] == "skipped"
    assert child.commands == []


@pytest.mark.feature("automation.rotation-rules")
def test_a_person_from_the_last_two_person_films_waits(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    # Only the person detectors: last year's pictures would also make a year and a month.
    config = write_config(tmp_path, automation={"detect_yearly": False, "backfill_months": False})
    last_year = date.today().year - 1
    library = Library().person("p-kid", "Kid").across(date(last_year, 3, 1), 20, 80, ("p-kid",))
    record_film(
        config,
        "person_spotlight",
        f"person_spotlight:{last_year - 3}-01-01:{last_year - 3}-12-31:kid",
        source="auto",
        category="birthday",
        people=("kid",),
        hours_ago=48,
    )

    result = _auto_run(config, library)

    assert result["outcome"] == "skipped"
    assert {r["rule"] for r in result["rejections"]} == {"person_in_last_two_person_runs"}
    assert child.commands == []


@pytest.mark.feature("automation.rotation-rules")
def test_a_category_twice_in_the_last_six_films_waits(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path)
    old = date.today().year - 2
    library = Library().month(f"{old}-05", 60)
    for back, category in ((96, "year_in_review"), (72, "year_in_review"), (48, "trip")):
        record_film(
            config,
            "year_in_review" if category == "year_in_review" else "trip",
            f"{category}:{old - 10 - back}-01-01:{old - 10 - back}-12-31:",
            source="auto",
            category=category,
            hours_ago=back,
        )

    result = _auto_run(config, library)

    assert result["outcome"] == "skipped"
    assert [r["rule"] for r in result["rejections"]] == ["category_limit_two_of_six"]
    assert child.commands == []


# ── failure backoff ──────────────────────────────────────────────────────


class _Clock:
    """Discovery's clock, ``ahead`` of the real one; the attempt history keeps real time."""

    ahead = timedelta(0)


@pytest.fixture
def later() -> Iterator[type[_Clock]]:
    class _Later(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return datetime.now(tz) + _Clock.ahead

    _Clock.ahead = timedelta(0)
    # WHY: the wall clock discovery weighs failure streaks against; time moves on in days.
    with patch("immich_memories.automation.candidate_discovery.datetime", _Later):
        yield _Clock


def _backing_off(config: Path) -> list[str]:
    printed = _printed_suggestions(config)
    return [line for line in printed.splitlines() if "Backing off" in line]


def _printed_suggestions(config: Path) -> str:
    with immich_holding(_only_last_month()):
        result = cli(config, "auto", "suggest")
    assert result.exit_code == 0, result.output
    return result.stdout


def _fail_once(config: Path) -> None:
    result = _auto_run(config, _only_last_month())
    assert result["outcome"] == "failed", result


@pytest.mark.feature("automation.failure-backoff")
def test_one_failure_is_not_held_against_a_candidate(
    tmp_path: Path, failing_child: _FailingChild
) -> None:
    config = write_config(tmp_path)
    _fail_once(config)

    assert _backing_off(config) == []
    assert _suggested_keys(config, _only_last_month()) != []


@pytest.mark.feature("automation.failure-backoff")
def test_two_failures_wait_24_hours_then_3_days_then_7(
    tmp_path: Path, failing_child: _FailingChild, later: type[_Clock]
) -> None:
    config = write_config(tmp_path)
    _fail_once(config)
    _fail_once(config)

    assert _suggested_keys(config, _only_last_month()) == []
    assert ["failed 2x, retrying after 24h" in line for line in _backing_off(config)] == [True]
    later.ahead = timedelta(hours=23)
    assert _suggested_keys(config, _only_last_month()) == []
    later.ahead = timedelta(hours=25)
    assert _suggested_keys(config, _only_last_month()) != []

    # Each failure below is stamped with the real clock, so the windows count from now.
    _fail_once(config)  # the third, once it came back
    later.ahead = timedelta(hours=71)
    assert ["failed 3x, retrying after 3d" in line for line in _backing_off(config)] == [True]
    later.ahead = timedelta(hours=73)
    assert _suggested_keys(config, _only_last_month()) != []

    _fail_once(config)  # the fourth
    later.ahead = timedelta(hours=167)
    assert ["failed 4x, retrying after 7d" in line for line in _backing_off(config)] == [True]
    later.ahead = timedelta(hours=169)
    assert _suggested_keys(config, _only_last_month()) != []


@pytest.mark.feature("automation.failure-backoff")
def test_a_success_clears_the_streak(tmp_path: Path, later: type[_Clock]) -> None:
    config = write_config(tmp_path)
    failing = _FailingChild(tmp_path / "films")
    working = FakeGenerateChild(tmp_path / "films")
    # WHY: the `generate` child process: it fails twice, then renders.
    with patch("immich_memories.automation.runner._execute_generate", failing):
        _fail_once(config)
        _fail_once(config)
    assert _backing_off(config) != []
    later.ahead = timedelta(hours=25)
    # WHY: the same child process, now rendering the film.
    with patch("immich_memories.automation.runner._execute_generate", working):
        made = _auto_run(config, _only_last_month(), "--force")

    assert made["outcome"] == "completed", made
    later.ahead = timedelta(0)
    assert _backing_off(config) == []


# ── skip reasons ─────────────────────────────────────────────────────────


@pytest.mark.feature("automation.skip-reasons")
def test_every_detector_that_found_nothing_says_why_above_the_table(tmp_path: Path) -> None:
    config = write_config(tmp_path, automation={"detect_trips": True, "detect_albums": False})
    library = Library().month("2026-05", 80)

    printed = suggest_text(config, library, date(2026, 6, 10))

    above, table = printed.split("Memory Candidates", 1)
    reasons = [line.strip("ℹ ").strip() for line in above.splitlines() if line.strip()]
    for detector in (
        "No year film:",
        "No person spotlight film:",
        "No people together film:",
        "No busy month film:",
        "No on this day film:",
        "No birthday film:",
        "No trip film: the home base is not set",
        "No special day film:",
        "No group film:",
        "No season film: the home base is not set",
        "No holiday film:",
        "No missed month film:",
        "No person month film:",
    ):
        assert any(reason.startswith(detector) for reason in reasons), (detector, reasons)
    # The monthly detector found its month; a switched-off detector has nothing to say.
    assert not any(reason.startswith(("No month film", "No album film")) for reason in reasons)
    assert "Monthly Highlights" in table


# ── the HTTP trigger ─────────────────────────────────────────────────────


def _settled(client: Any, status_url: str) -> dict[str, Any]:
    for _ in range(400):
        payload = client.get(status_url, headers={"x-api-key": TOKEN}).json()
        if payload["state"] != "running":
            return payload
        asyncio.run(asyncio.sleep(0.02))
    raise AssertionError(f"the triggered attempt never finished: {payload}\n{_thread_stacks()}")


def _thread_stacks() -> str:
    """Where every thread of this process is: the run's own thread says why it never ended."""
    import sys
    import threading
    import traceback

    names = {thread.ident: thread.name for thread in threading.enumerate()}
    return "\n".join(
        f"--- {names.get(ident, ident)}\n{''.join(traceback.format_stack(frame))}"
        for ident, frame in sys._current_frames().items()
    )


@pytest.fixture
def trigger_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from immich_memories.config.loader import load_config
    from tests.web_server_fixtures import server_client

    path = write_config(tmp_path, server={"trigger_token": TOKEN})
    return path, server_client(monkeypatch, load_config(path))


@pytest.mark.feature("automation.trigger-api")
def test_a_trigger_makes_the_film_auto_run_would_choose(
    trigger_server, child: FakeGenerateChild
) -> None:
    path, client = trigger_server
    best = _suggested_keys(path, _two_candidates())[0]

    with immich_holding(_two_candidates()):
        accepted = client.post("/api/trigger", headers={"x-api-key": TOKEN})
        assert accepted.status_code == 202, accepted.text
        settled = _settled(client, accepted.json()["status_url"])

    assert settled["state"] == "completed", settled
    assert settled["run"]["status"] == "completed"
    assert _asked_for(child) == [best]


@pytest.mark.feature("automation.trigger-api")
def test_a_trigger_inside_the_cooldown_is_skipped_like_the_daily_run(
    trigger_server, child: FakeGenerateChild
) -> None:
    path, client = trigger_server
    _auto_run(path, _two_candidates())

    with immich_holding(_two_candidates()):
        accepted = client.post("/api/trigger", headers={"authorization": f"Bearer {TOKEN}"})
        settled = _settled(client, accepted.json()["status_url"])

    assert accepted.status_code == 202
    assert (settled["state"], settled["reason"]) == ("skipped", "cooldown active")
    assert len(child.commands) == 1


@pytest.mark.feature("automation.trigger-api")
def test_a_wrong_token_starts_nothing(trigger_server, child: FakeGenerateChild) -> None:
    from immich_memories.automation.state_store import AutomationStateStore
    from immich_memories.config.loader import Config
    from immich_memories.db import open_store

    path, client = trigger_server

    refused = client.post("/api/trigger", headers={"x-api-key": "not-" + TOKEN})

    assert refused.status_code == 401
    assert refused.json() == {"detail": "invalid trigger token"}
    assert AutomationStateStore(open_store(Config.from_yaml(path))).get_last_attempt() is None
    assert child.commands == []


# ── the daily timer ──────────────────────────────────────────────────────


def _today_at(hour: int, minute: int = 0) -> datetime:
    # The store stamps attempts with the real clock, so the timer's day is today.
    return datetime.now().astimezone().replace(hour=hour, minute=minute, second=0, microsecond=0)


def _timer(config: Path, clock: list[datetime]):
    from immich_memories.automation.in_process_scheduler import InProcessScheduler
    from immich_memories.config.loader import load_config

    loaded = load_config(config)
    return InProcessScheduler(lambda: loaded, clock=lambda: clock[0])


@pytest.mark.feature("scheduler.docker-timer")
def test_the_timer_makes_one_film_at_daily_at_and_no_more_that_day(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path, automation={"enabled": True, "daily_at": "09:00"})
    clock = [_today_at(8, 59)]
    timer = _timer(config, clock)

    fired = []
    with immich_holding(_two_candidates()):
        for at in (
            _today_at(8, 59),
            _today_at(9, 0),
            _today_at(9, 1),
            _today_at(15),
            _today_at(23, 59),
        ):
            clock[0] = at
            fired.append(asyncio.run(timer.tick()))

    assert fired == [False, True, False, False, False]
    assert len(child.commands) == 1
    assert timer.snapshot().last_outcome == "completed"
    assert timer.snapshot().next_run == _today_at(9) + timedelta(days=1)


@pytest.mark.feature("scheduler.docker-timer")
def test_a_server_down_at_daily_at_catches_up_when_it_starts(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path, automation={"enabled": True, "daily_at": "09:00"})

    with immich_holding(_two_candidates()):
        fired = asyncio.run(_timer(config, [_today_at(14)]).tick())

    assert fired
    assert len(child.commands) == 1


@pytest.mark.feature("scheduler.docker-timer")
def test_a_restart_after_the_days_run_waits_for_tomorrow(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path, automation={"enabled": True, "daily_at": "09:00"})
    _auto_run(config, _two_candidates())  # `docker compose exec ... auto run` this morning

    restarted = _timer(config, [_today_at(14)])
    with immich_holding(_two_candidates()):
        fired = asyncio.run(restarted.tick())

    assert not fired
    assert len(child.commands) == 1
    assert restarted.snapshot().next_run == _today_at(9) + timedelta(days=1)


@pytest.mark.feature("scheduler.docker-timer")
def test_without_automation_enabled_the_timer_never_fires(
    tmp_path: Path, child: FakeGenerateChild
) -> None:
    config = write_config(tmp_path, automation={"daily_at": "09:00"})

    with immich_holding(_two_candidates()):
        fired = asyncio.run(_timer(config, [_today_at(14)]).tick())

    assert not fired
    assert child.commands == []


@pytest.fixture
def web_timer() -> Iterator[None]:
    """The web process's own timer, put back as it was after the test."""
    from immich_memories.automation.in_process_scheduler import automation_scheduler

    saved = dict(vars(automation_scheduler))
    yield
    vars(automation_scheduler).clear()
    vars(automation_scheduler).update(saved)


@pytest.mark.feature("scheduler.docker-timer")
def test_the_web_process_runs_the_daily_decision_when_it_starts(
    tmp_path: Path, child: FakeGenerateChild, web_timer: None
) -> None:
    from starlette.testclient import TestClient

    from immich_memories.automation.state_store import AutomationStateStore
    from immich_memories.config.loader import load_config
    from immich_memories.db import open_store
    from immich_memories.web.server import create_app

    # A daily_at long gone: the server starts after it, so it catches up at once. The
    # readiness probe's own Immich call reaches a loopback server that answers at once.
    probe = LocalHttp()
    path = write_config(
        tmp_path, immich_url=probe.url, automation={"enabled": True, "daily_at": "00:00"}
    )
    config = load_config(path)
    state = AutomationStateStore(open_store(config))

    with immich_holding(_two_candidates()), TestClient(create_app()) as client:
        for _ in range(400):
            last = state.get_last_attempt()
            if last is not None and last.outcome is not AutoOutcome.RUNNING:
                break
            asyncio.run(asyncio.sleep(0.02))
        health = client.get("/health/ready").json()
    probe.close()

    assert last is not None and last.outcome is AutoOutcome.COMPLETED, last
    assert last.reason.startswith("generation completed")
    assert len(child.commands) == 1
    assert health["in_process_scheduler"]["enabled"] is True
    assert health["in_process_scheduler"]["last_outcome"] == "completed"
