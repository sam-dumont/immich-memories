"""`auto install` on macOS asks launchd itself whether the job can reach a LAN Immich (#2242).

The permission is keyed to the resolved interpreter and checked when launchd starts the job, so
only a job started by launchd can answer. The launchctl boundary is faked; the plist and the
command it runs are real.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

from immich_memories.automation import local_network_check as check

SHIM = Path("/Users/me/.immich-memories/bin/immich-memories-auto")
PYTHON = "/Users/me/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/bin/python3.12"


class FakeLaunchd:
    """Stands in for launchctl: `bootstrap` runs the job the way launchd would, then leaves."""

    def __init__(self, exit_code: int | None, *, bootstrap_fails: bool = False) -> None:
        self.exit_code = exit_code
        self.bootstrap_fails = bootstrap_fails
        self.calls: list[list[str]] = []
        self.plists: list[dict] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        if args[0] == "bootstrap":
            if self.bootstrap_fails:
                return subprocess.CompletedProcess(args, 5, "", "Bootstrap failed: 5")
            plist = plistlib.loads(Path(args[-1]).read_bytes())
            self.plists.append(plist)
            if self.exit_code is not None:
                # The job's own shell writes its exit status where the plist said to.
                script = plist["ProgramArguments"][2]
                target = script.rsplit(">", 1)[1].strip().strip("'")
                Path(target).write_text(f"{self.exit_code}\n")
        return subprocess.CompletedProcess(args, 0, "", "")


def _run(tmp_path: Path, launchd: FakeLaunchd, **kwargs):
    ticks = iter(range(0, 1000))
    return check.run_check(
        shim=SHIM,
        config_path=kwargs.pop("config_path", None),
        state_dir=tmp_path,
        uid=501,
        interpreter=PYTHON,
        launchctl=launchd,
        sleep=lambda _s: None,
        clock=lambda: float(next(ticks)),
        wait_seconds=20,
        **kwargs,
    )


def test_the_check_runs_the_shim_with_a_ping_only_command_at_load(tmp_path):
    launchd = FakeLaunchd(0)

    _run(tmp_path, launchd, config_path=Path("/Users/me/c.yaml"))

    plist = launchd.plists[0]
    assert plist["RunAtLoad"] is True
    assert "StartCalendarInterval" not in plist
    assert plist["Label"] == check.CHECK_LABEL != "com.immich-memories.auto"
    argv = plist["ProgramArguments"]
    assert argv[:2] == ["/bin/sh", "-c"]
    # "$0" is the shim and the rest is `--config PATH config test`: nothing is searched or filmed.
    assert argv[3:] == [str(SHIM), "--config", "/Users/me/c.yaml", "config", "test"]


def test_exit_zero_is_a_pass_and_the_agent_is_removed(tmp_path):
    launchd = FakeLaunchd(0)

    outcome = _run(tmp_path, launchd)

    assert outcome.passed and outcome.started
    assert [call[0] for call in launchd.calls] == ["bootstrap", "bootout"]
    assert launchd.calls[1][1] == f"gui/501/{check.CHECK_LABEL}"
    assert not Path(launchd.calls[0][-1]).exists()


def test_a_failing_job_names_the_interpreter_and_where_to_allow_it(tmp_path):
    outcome = _run(tmp_path, FakeLaunchd(1))

    assert not outcome.passed and outcome.started
    assert PYTHON in outcome.advice
    assert "System Settings > Privacy & Security > Local Network" in outcome.advice


def test_a_failing_check_says_to_answer_the_prompt_on_the_macs_screen(tmp_path):
    # An unanswered prompt is a no: the fix is clicking Allow on the Mac, then checking again.
    outcome = _run(tmp_path, FakeLaunchd(1))

    assert f'"{Path(PYTHON).name}"' in outcome.advice
    assert "on this Mac's screen" in outcome.advice
    assert "click Allow" in outcome.advice
    assert "auto install` again" in outcome.advice


def test_a_job_that_never_answers_fails_after_the_wait(tmp_path):
    launchd = FakeLaunchd(None)

    outcome = _run(tmp_path, launchd)

    assert not outcome.passed and outcome.started and outcome.timed_out
    assert launchd.calls[-1][0] == "bootout", "the agent is removed even when nothing answered"


def test_a_check_that_could_not_start_is_not_blamed_on_the_permission(tmp_path):
    outcome = _run(tmp_path, FakeLaunchd(0, bootstrap_fails=True))

    assert not outcome.started and not outcome.passed
    assert "Local Network" not in outcome.advice


@pytest.mark.parametrize(
    ("url", "gated"),
    [
        ("http://192.168.1.20:2283", True),
        ("http://10.0.0.5", True),
        ("http://nas.local:2283", True),
        ("http://localhost:2283", False),
        ("http://127.0.0.1:2283", False),
        ("https://photos.example.com", False),
        ("", False),
    ],
)
def test_only_a_private_address_is_gated(url, gated, monkeypatch):
    # WHY: a bare public name would otherwise be resolved over the network.
    monkeypatch.setattr("immich_memories.api.local_network.socket.getaddrinfo", lambda *_args: [])
    assert check.immich_is_on_the_local_network(url) is gated


def test_the_resolved_interpreter_is_recorded_and_a_change_is_reported(tmp_path):
    outcome = _run(tmp_path, FakeLaunchd(0))
    check.record_check(tmp_path, outcome)

    assert check.interpreter_note(tmp_path, current=PYTHON) is None
    note = check.interpreter_note(
        tmp_path, current="/Users/me/.local/share/uv/python/cpython-3.12.15/bin/python3.12"
    )
    assert note is not None
    assert PYTHON in note and "cpython-3.12.15" in note
    assert "auto install" in note


def test_nothing_is_said_before_a_check_was_ever_recorded(tmp_path):
    assert check.interpreter_note(tmp_path, current=PYTHON) is None
