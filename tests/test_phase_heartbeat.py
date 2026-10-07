"""A long phase says it is alive at least every interval, with the count it last knew (#2219)."""

from __future__ import annotations

from immich_memories.operations.phase_heartbeat import PhaseHeartbeat
from immich_memories.operations.phases import OperationalPhase


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _heartbeat(clock: _Clock, sent: list) -> PhaseHeartbeat:
    return PhaseHeartbeat(lambda *event: sent.append(event), interval_seconds=60.0, clock=clock)


def test_a_quiet_phase_repeats_itself_with_its_last_count_once_the_interval_passes() -> None:
    clock, sent = _Clock(), []
    heartbeat = _heartbeat(clock, sent)
    heartbeat.note(OperationalPhase.RENDER, 12, 149, "Rendering memory")

    clock.now += 59
    assert heartbeat.tick() is False
    clock.now += 2
    assert heartbeat.tick() is True

    phase, current, total, message = sent[0]
    assert (phase, current, total) == (OperationalPhase.RENDER, 12, 149)
    assert message.startswith("Rendering memory")
    assert "still working" in message
    assert "1m" in message


def test_a_phase_that_keeps_reporting_never_needs_a_heartbeat() -> None:
    clock, sent = _Clock(), []
    heartbeat = _heartbeat(clock, sent)
    for step in range(5):
        clock.now += 50
        heartbeat.note(OperationalPhase.SELECTION, step, 5, "Reading")
        assert heartbeat.tick() is False

    assert sent == []


def test_the_beats_keep_coming_every_interval_and_count_the_time_in_the_step() -> None:
    clock, sent = _Clock(), []
    heartbeat = _heartbeat(clock, sent)
    heartbeat.note(OperationalPhase.SELECTION, 0, 0, "149 pictures going into the picture review")

    for _ in range(3):
        clock.now += 61
        assert heartbeat.tick() is True

    assert len(sent) == 3
    assert "3m" in sent[-1][3]
    assert sent[-1][3].count("still working") == 1


def test_nothing_beats_before_the_first_phase_or_after_completion() -> None:
    clock, sent = _Clock(), []
    heartbeat = _heartbeat(clock, sent)

    clock.now += 600
    assert heartbeat.tick() is False

    heartbeat.note(OperationalPhase.COMPLETE, 1, 1, "Complete")
    clock.now += 600
    assert heartbeat.tick() is False
    assert sent == []


def test_a_failing_emit_never_stops_the_beat() -> None:
    clock = _Clock()

    def broken(*_event) -> None:
        raise OSError("store went away")

    heartbeat = PhaseHeartbeat(broken, interval_seconds=60.0, clock=clock)
    heartbeat.note(OperationalPhase.RENDER, 0, 3, "Rendering memory")
    clock.now += 61

    assert heartbeat.tick() is True


def test_the_thread_beats_on_its_own_and_stops_cleanly() -> None:
    import threading

    beat = threading.Event()
    heartbeat = PhaseHeartbeat(lambda *_event: beat.set(), interval_seconds=0.02)
    heartbeat.note(OperationalPhase.RENDER, 0, 3, "Rendering memory")

    heartbeat.start()
    try:
        assert beat.wait(2)
    finally:
        heartbeat.stop()


def test_a_scheduled_attempt_keeps_getting_phase_events_while_its_phase_works(tmp_path) -> None:
    """The events land on the attempt row, which is what the app log reads (#2219)."""
    import time
    from unittest.mock import MagicMock

    from immich_memories.automation.state_store import AutomationStateStore
    from immich_memories.cli.attempt_phase_reporter import AttemptPhaseReporter
    from immich_memories.config_loader import Config

    config = Config(
        cache={"database": str(tmp_path / "a.db"), "directory": str(tmp_path / "cache")}
    )
    store = AutomationStateStore()
    attempt = store.start_attempt(reason="daily wake")
    # WHY: the rich terminal progress bar, which a unit test has no terminal for.
    reporter = AttemptPhaseReporter(config, attempt.id, MagicMock(), 0, heartbeat_seconds=0.05)

    reporter.heartbeat.start()
    try:
        reporter.emit(
            OperationalPhase.SELECTION, 0, 149, "Editing the memory: going into the family check"
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            events = store.get_attempt(attempt.id).phase_events
            if len(events) >= 3:
                break
            time.sleep(0.05)
    finally:
        reporter.heartbeat.stop()

    beats = [e for e in events if "still working" in e["message"]]
    assert len(beats) >= 2
    assert all(e["total"] == 149 and e["phase"] == "selection" for e in beats)
