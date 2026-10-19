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

    def read(after):
        seen.set()
        return [(i, event) for i, event in enumerate(events, 1) if i > after]

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
    def read(after):
        raise OSError("store went away")

    with log_phase_progress(read, interval_seconds=0.01):
        pass


def test_each_poll_asks_only_for_what_came_after_the_last_event_it_saw():
    asked = []
    log = [(1, _event("download", 1, 3, "a")), (2, _event("download", 2, 3, "b"))]
    stop = threading.Event()

    def read(after):
        asked.append(after)
        stop.set()
        return [item for item in log if item[0] > after]

    with log_phase_progress(read, interval_seconds=0.01):
        stop.wait(2)
        log.append((3, _event("render", 0, 0, "c")))
    assert asked[0] == 0
    assert asked[-1] == 2  # the final drain starts past the events already logged
