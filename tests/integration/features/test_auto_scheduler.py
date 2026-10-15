"""Automation's own commands: status and history, the scheduler files, accounts and groups,
and the test notification.

Every command is the real CLI in a child process with its own sealed HOME. `auto install`
only ever writes files under that HOME (the launcher and the scheduler's unit files) and
prints the commands that would activate them; it is never let near the machine's real
launchd, systemd or crontab. Which scheduler it targets is pinned per test, the way the
operating system would choose it, so each test reads the same on macOS and Linux.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.features.automation_library import LocalHttp
from tests.features.cli_harness import CliResult, OutboundTrap, UserHome, basic_config
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import QUIET_DAY, day_args, render
from tests.integration.features.test_automation_delivery import _run

UNREACHABLE = "http://127.0.0.1:9"  # discard port: refused at once, no DNS

# Pin the scheduler the operating system would pick (argv[1]), then run the real CLI.
_SCHEDULER_CHILD = """
import sys
from unittest.mock import patch

platform = sys.argv[1]
# WHY: the operating system's scheduler: launchd on macOS, systemd where systemctl exists,
# crontab elsewhere. Pinned so each install writes only under the sealed HOME.
patch(
    "immich_memories.automation.system_scheduler.detect_platform", lambda: platform
).start()

from immich_memories.cli import main

sys.argv = ["immich-memories", *sys.argv[2:]]
main()
"""


def _on(platform: str, home: UserHome, bin_dir: Path, *args: str) -> CliResult:
    """`immich-memories <args>` with `platform` as the scheduler and `bin_dir` first on PATH."""
    env = {"PATH": os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])}
    completed = subprocess.run(  # noqa: S603 -- our own CLI, fixed argv
        [sys.executable, "-c", _SCHEDULER_CHILD, platform, *args],
        capture_output=True,
        text=True,
        timeout=300,
        env=home.env(env),
        cwd=home.root,
        check=False,
    )
    return CliResult(tuple(args), completed.returncode, completed.stdout, completed.stderr)


def _git(checkout: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed git argv
        ["git", "-C", str(checkout), *args], check=True, capture_output=True, text=True
    )


def _installed_binary(checkout: Path) -> Path:
    """An `immich-memories` executable inside `checkout`, as an editable install leaves it."""
    binary = checkout / ".venv" / "bin" / "immich-memories"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return binary


def _worktree_checkout(root: Path) -> Path:
    """A linked git worktree: its `.git` is a file pointing into `<repo>/.git/worktrees/`."""
    checkout = root / "worktree"
    checkout.mkdir(parents=True)
    (checkout / ".git").write_text(f"gitdir: {root / 'repo' / '.git' / 'worktrees' / 'w'}\n")
    _installed_binary(checkout)
    return checkout


def _checkout_behind_its_upstream(root: Path) -> Path:
    """A clone one commit behind the branch it tracks, its upstream already fetched."""
    origin = root / "origin"
    origin.mkdir(parents=True)
    _git(origin, "init", "-q", "-b", "main")
    identity = ("-c", "user.name=Kit", "-c", "user.email=kit@example.test")
    _git(origin, *identity, "commit", "-q", "--allow-empty", "-m", "first")
    clone = root / "clone"
    subprocess.run(  # noqa: S603 -- fixed git argv
        ["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True
    )
    _git(origin, *identity, "commit", "-q", "--allow-empty", "-m", "second")
    _git(clone, "fetch", "-q")
    _installed_binary(clone)
    return clone


@pytest.fixture
def home(tmp_path: Path) -> UserHome:
    home = UserHome(tmp_path / "home")
    home.write_config(basic_config(UNREACHABLE, "a-key", home))
    return home


def _systemd_files(home: UserHome) -> list[Path]:
    unit_dir = home.root / ".config" / "systemd" / "user"
    return sorted(unit_dir.glob("immich-memories-auto.*")) if unit_dir.exists() else []


def _launcher(home: UserHome) -> Path:
    return home.root / ".immich-memories" / "bin" / "immich-memories-auto"


# ── auto install refuses stale code ──────────────────────────────────────────


@pytest.mark.feature("scheduler.auto-install-refuses-stale")
def test_auto_install_refuses_a_worktree_unless_forced(home: UserHome, tmp_path: Path):
    checkout = _worktree_checkout(tmp_path / "code")
    bin_dir = checkout / ".venv" / "bin"

    refused = _on("systemd", home, bin_dir, "auto", "install")
    nothing_written = not _launcher(home).exists() and _systemd_files(home) == []
    forced = _on("systemd", home, bin_dir, "auto", "install", "--force")

    assert refused.returncode == 1, refused.explain()
    assert "linked git worktree" in refused.output, refused.explain()
    assert nothing_written
    assert forced.returncode == 0, forced.explain()
    assert "Installed systemd scheduler" in forced.output
    assert [p.name for p in _systemd_files(home)] == [
        "immich-memories-auto.service",
        "immich-memories-auto.timer",
    ]
    assert str(bin_dir) in _launcher(home).read_text()


@pytest.mark.feature("scheduler.auto-install-refuses-stale")
def test_auto_install_refuses_a_checkout_behind_its_upstream(home: UserHome, tmp_path: Path):
    checkout = _checkout_behind_its_upstream(tmp_path / "code")

    refused = _on("systemd", home, checkout / ".venv" / "bin", "auto", "install")

    assert refused.returncode == 1, refused.explain()
    assert re.search(r"1 commit\(s\) behind origin/main", refused.output), refused.explain()
    assert not _launcher(home).exists()
    assert _systemd_files(home) == []


# ── uninstall ────────────────────────────────────────────────────────────────


@pytest.mark.feature("scheduler.auto-uninstall")
def test_auto_install_uninstall_deletes_the_launcher_and_the_scheduler_files(
    home: UserHome, tmp_path: Path
):
    bin_dir = _installed_binary(tmp_path / "code").parent
    installed = _on("systemd", home, bin_dir, "auto", "install", "--hour", "4")
    assert installed.returncode == 0, installed.explain()
    written = [_launcher(home), *_systemd_files(home)]
    assert len(written) == 3 and all(path.is_file() for path in written)

    removed = _on("systemd", home, bin_dir, "auto", "install", "--uninstall")
    again = _on("systemd", home, bin_dir, "auto", "install", "--uninstall")

    assert removed.returncode == 0, removed.explain()
    assert "Scheduler removed" in removed.output
    assert not any(path.exists() for path in written)
    assert again.returncode == 0, again.explain()
    assert "No scheduler found to remove" in again.output


# ── crontab ──────────────────────────────────────────────────────────────────


@pytest.mark.feature("scheduler.crontab")
def test_without_launchd_or_systemd_auto_install_prints_a_crontab_line_to_paste(
    home: UserHome, tmp_path: Path
):
    bin_dir = _installed_binary(tmp_path / "code").parent

    result = _on("crontab", home, bin_dir, "auto", "install", "--hour", "6", "--minute", "15")

    assert result.returncode == 0, result.explain()
    assert "Installed crontab scheduler" in result.output
    launcher = _launcher(home)
    activate = re.search(r"Activate:\s+(.+)", result.stdout)
    assert activate, result.explain()
    # The line to paste: 06:15 every day, running the launcher's `auto run`.
    line = re.search(r"'(15 6 \* \* \* \S+ auto run[^']*)'", activate.group(1))
    assert line, activate.group(1)
    assert line.group(1).split()[5] == str(launcher)
    assert "| crontab -" in activate.group(1)
    assert re.search(r"Deactivate:\s+crontab -l \| grep -Fv", result.stdout)
    # Nothing is written but the launcher the line runs; no unit files, no crontab edit.
    assert launcher.is_file()
    assert _systemd_files(home) == []
    assert not (home.root / "Library" / "LaunchAgents").exists()


# ── auto status and history ──────────────────────────────────────────────────


@pytest.mark.feature("automation.status-history")
def test_auto_status_and_history_show_the_last_attempt_and_the_automatic_films(
    tmp_path: Path, immich: LibraryServer, outbound_trap: OutboundTrap
):
    home = UserHome(tmp_path / "home", extra_env=tuple(outbound_trap.env().items()))
    home.write_config(basic_config(immich.base_url, immich.api_key, home))
    before = _run(home, "auto", "history")
    by_hand = render(home, *day_args(QUIET_DAY))
    rows = json.loads(_run(home, "auto", "suggest", "--json", "--limit", "50").stdout)
    album = next(row for row in rows if row["category"] == "album")

    ran = _run(home, "auto", "run", "--candidate", album["memory_key"], "--quiet", scripted=True)
    status = _run(home, "auto", "status")
    as_json = _run(home, "auto", "status", "--json")
    history = _run(home, "auto", "history", "--limit", "5")
    none_shown = _run(home, "auto", "history", "--limit", "0")

    assert "No auto-generated memories found" in before.output
    assert ran.returncode == 0, ran.explain()
    decision = json.loads(ran.stdout.strip().splitlines()[-1])
    assert decision["outcome"] == "completed", ran.explain()
    data = json.loads(as_json.stdout)
    assert data["last_attempt"]["outcome"] == "completed"
    run_id = data["last_completed_auto_run"]["run_id"]
    assert data["last_completed_auto_run"]["category"] == "album"
    assert data["scheduler"]["platform"] in {"launchd", "systemd", "crontab"}
    assert data["scheduler"]["summary"]
    assert status.returncode == 0, status.explain()
    assert f"Scheduler: {data['scheduler']['summary']}" in status.output
    assert "Last attempt: completed" in status.output
    assert f"Last completed auto run: {run_id} (album)" in status.output
    # History lists the automatic film, not the one made by hand.
    assert history.returncode == 0, history.explain()
    assert re.search(r"│ album\s+│ 2025-07-12 to 2025-07-31", history.stdout), history.explain()
    assert by_hand.film.name not in history.stdout
    assert "album" not in none_shown.stdout


# ── accounts and saved groups ────────────────────────────────────────────────

# The fixture library's last year, seen from a day the year after.
_NEXT_YEAR = "2026-03-02"
_YEAR = "year_in_review:2025-01-01:2025-12-31:"


def _with_partner(home: UserHome, immich: LibraryServer, accounts: list[str]) -> UserHome:
    config = basic_config(immich.base_url, immich.api_key, home)
    config["immich"]["accounts"] = {
        "partner": {"url": immich.base_url, "api_key": immich.partner_api_key}
    }
    config["advanced"]["automation"] = {"accounts": accounts, "detect_groups": True}
    home.write_config(config)
    grouped = _run(
        home,
        "people",
        "group",
        "add",
        "kit-and-charlie",
        f'"{immich.person_of("person-kit")}" OR "{immich.person_of("person-charlie")}"',
    )
    assert grouped.returncode == 0, grouped.explain()
    return home


def _proposals(home: UserHome) -> dict[str, dict]:
    result = _run(home, "auto", "suggest", "--json", "--limit", "50", today=_NEXT_YEAR)
    assert result.returncode == 0, result.explain()
    return {row["memory_key"]: row for row in json.loads(result.stdout)}


def _would_run(home: UserHome, key: str) -> str:
    result = _run(home, "auto", "run", "--dry-run", "--candidate", key, today=_NEXT_YEAR)
    assert result.returncode == 0, result.explain()
    line = re.search(r"would execute: (.+)", result.output)
    assert line, result.explain()
    return line.group(1)


@pytest.mark.feature("automation.accounts-and-groups")
def test_automation_reads_exactly_the_named_accounts_and_proposes_each_saved_group(
    tmp_path: Path, immich: LibraryServer, outbound_trap: OutboundTrap
):
    def home_reading(name: str, accounts: list[str]) -> UserHome:
        home = UserHome(tmp_path / name, extra_env=tuple(outbound_trap.env().items()))
        return _with_partner(home, immich, accounts)

    primary, partner, both = (
        home_reading("primary", []),
        home_reading("partner", ["partner"]),
        home_reading("both", ["primary", "partner"]),
    )
    on_primary, on_partner, on_both = _proposals(primary), _proposals(partner), _proposals(both)

    def group_films(rows: dict[str, dict]) -> list[dict]:
        return [r for r in rows.values() if r["reason"].startswith("Saved group 'kit-and-charlie'")]

    def of(rows: dict[str, dict], category: str) -> list[dict]:
        return [r for r in rows.values() if r["category"] == category]

    # Empty reads the primary alone; the partner alone leaves the primary's library out,
    # its trip and its album with it; both read both.
    year = on_primary[_YEAR]["asset_count"]
    assert on_partner[_YEAR]["asset_count"] < year < on_both[_YEAR]["asset_count"]
    assert of(on_partner, "trip") == [] and of(on_partner, "album") == []
    assert of(on_both, "trip") == of(on_primary, "trip") != []
    # The scope travels to the film's own run.
    assert "--accounts" not in _would_run(primary, _YEAR)
    assert "--accounts=partner " in _would_run(partner, _YEAR)
    assert "--accounts=primary,partner " in _would_run(both, _YEAR)
    # One film of last year for the saved group, where its people are pictured.
    (group,) = group_films(on_primary)
    assert (group["memory_type"], group["date_range"]) == (
        "multi_person",
        "2025-01-01 to 2025-12-31",
    )
    assert len(group_films(on_both)) == 1
    # None of the group's people is among the partner's most pictured: no group film there.
    assert group_films(on_partner) == []


# ── the test notification ────────────────────────────────────────────────────


@pytest.fixture
def sinks() -> Iterator[tuple[LocalHttp, LocalHttp]]:
    first, second = LocalHttp(), LocalHttp()
    yield first, second
    first.close()
    second.close()


def _json_target(sink: LocalHttp) -> str:
    return f"json://127.0.0.1:{sink.url.rsplit(':', 1)[1]}/"


@pytest.mark.feature("notifications.test")
def test_auto_test_notification_sends_a_message_to_each_configured_target(
    home: UserHome, sinks: tuple[LocalHttp, LocalHttp]
):
    config = basic_config(UNREACHABLE, "a-key", home)
    config["advanced"]["notifications"] = {
        "enabled": True,
        "urls": [_json_target(sink) for sink in sinks],
    }
    home.write_config(config)

    sent = home.run("auto", "test-notification")
    # Sent on purpose: a second test right after is not held back by the cooldown.
    again = home.run("auto", "test-notification")

    assert sent.returncode == 0, sent.explain()
    assert "Test notification sent successfully" in sent.output
    assert "Test notification sent successfully" in again.output
    for sink in sinks:
        messages = sink.posted()
        assert len(messages) == 2, messages
        assert all(m["title"] and m["message"] for m in messages), messages


@pytest.mark.feature("notifications.test")
def test_auto_test_notification_says_so_when_off_or_when_the_target_fails(home: UserHome):
    off = home.run("auto", "test-notification")
    config = basic_config(UNREACHABLE, "a-key", home)
    config["advanced"]["notifications"] = {"enabled": True, "urls": ["json://127.0.0.1:9/"]}
    home.write_config(config)

    failed = home.run("auto", "test-notification")

    assert "Notifications are disabled" in off.output, off.explain()
    assert "Test notification failed" in failed.output, failed.explain()
    assert "sent successfully" not in failed.output
    # A script reads the exit code: nothing sent is a failure, whatever the reason.
    assert off.returncode == 1, off.explain()
    assert failed.returncode == 1, failed.explain()
