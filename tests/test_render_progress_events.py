"""A render reports its activity without converting encoder time into invented clip counts."""

from __future__ import annotations

from immich_memories.generate_progress import render_progress_events
from immich_memories.operations.phases import OperationalPhase


class _Operational:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def observe(self, phase, current, total, message):
        pass

    def emit(self, phase, current, total, message):
        self.events.append((phase, current, total, message))


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def test_assembly_progress_becomes_render_events_at_most_every_interval() -> None:
    operational, clock, inner = _Operational(), _Clock(), []
    callback = render_progress_events(
        lambda pct, msg: inner.append((pct, msg)), operational, 149, clock=clock, every_seconds=30
    )

    callback(0.0, "Encoding video...")
    clock.now = 10
    callback(0.1, "Encoding video...")
    clock.now = 31
    callback(0.5, "Encoding video...")

    assert [e[1] for e in operational.events] == [0, 0]
    assert all(e[0] is OperationalPhase.RENDER and e[2] == 0 for e in operational.events)
    assert len(inner) == 3, "the progress bar still hears every report"


def test_a_render_with_no_progress_bar_still_reports_events() -> None:
    operational = _Operational()
    callback = render_progress_events(None, operational, 10, clock=_Clock(), every_seconds=30)

    callback(1.0, "Done")

    assert operational.events == [(OperationalPhase.RENDER, 0, 0, "Done")]


def test_clip_preparation_says_which_clip_n_of_total_instead_of_the_finished_selection() -> None:
    from immich_memories.generate_progress import clip_preparation_events

    operational, clock, inner = _Operational(), _Clock(), []
    callback = clip_preparation_events(
        lambda _stage, _pct, msg: inner.append(msg),
        operational,
        OperationalPhase.RENDER,
        10,
        clock=clock,
        every_seconds=30,
    )

    callback("extract", 0.0, "Downloading: a.mov")
    clock.now = 10
    callback("extract", 0.35, "Downloading: b.mov")
    clock.now = 31
    callback("extract", 0.35, "Prepared 5/10 sources")

    assert operational.events == [
        (OperationalPhase.RENDER, 0, 10, "Preparing clips (0/10)"),
        (OperationalPhase.RENDER, 5, 10, "Preparing clips (5/10)"),
    ]
    assert len(inner) == 3, "the progress bar still hears every report"


def test_a_quiet_audio_mix_never_repeats_an_older_encoding_percentage(tmp_path) -> None:
    from unittest.mock import create_autospec

    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_progress import _OperationalProgress
    from immich_memories.operations.phase_heartbeat import PhaseHeartbeat
    from immich_memories.tracking.run_tracker import RunTracker

    clock, beats = _Clock(), []
    heartbeat = PhaseHeartbeat(lambda *event: beats.append(event), clock=clock)
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=Config(),
        phase_callback=lambda event: heartbeat.note(
            event.phase, event.current, event.total, event.message
        ),
    )
    # WHY: persistence is a boundary; the observer must update without another store write.
    tracker = create_autospec(RunTracker, instance=True)
    callback = render_progress_events(None, _OperationalProgress(params, tracker), 15, clock=clock)
    callback(0.83, "Encoding: 83%")
    clock.now = 1
    callback(1.0, "Mixing audio...")
    clock.now = 32
    assert heartbeat.tick()

    assert beats[-1][1:3] == (0, 0)
    assert beats[-1][3].startswith("Mixing audio...")
    assert tracker.record_phase_event.call_count == 1
