"""A scheduled run says where it is in the app log while the generation child works."""

import logging
import threading

from immich_memories.automation.phase_log import log_phase_progress


def _event(phase, current, total, message):
    return {
        "phase": phase,
        "label": phase.title(),
        "current": current,
        "total": total,
        "message": message,
        "elapsed_seconds": 12.0,
    }


def test_each_phase_the_child_reports_reaches_the_app_log_once(caplog):
    events = [_event("download", 3, 40, "Extracting clips")]
    seen = threading.Event()

    def read():
        seen.set()
        return list(events)

    with (
        caplog.at_level(logging.INFO, logger="immich_memories.automation.phase_log"),
        log_phase_progress(read, interval_seconds=0.01),
    ):
        seen.wait(2)
        events.append(_event("render", 0, 0, "Assembling"))
        # leaving the block reads once more, so a phase finished between polls is not lost

    lines = [r.getMessage() for r in caplog.records]
    assert sum("Download" in line and "3/40" in line for line in lines) == 1
    assert sum("Render" in line for line in lines) == 1


def test_a_failing_read_never_stops_the_run(caplog):
    def read():
        raise OSError("store went away")

    with log_phase_progress(read, interval_seconds=0.01):
        pass
