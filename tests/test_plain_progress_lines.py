"""Without a terminal, a counted stage logs its start, its quarters and its end (#2161).

A cron or log-file run printed one progress line per picture: about 900 lines for 135
pictures, which also filled the pasted run report (#2127).
"""

from __future__ import annotations

import logging

from immich_memories.cli._live_display import QuietDisplay


def _logged(caplog, descriptions: list[str]) -> list[str]:
    with caplog.at_level(logging.INFO, logger="immich_memories.progress"):
        display = QuietDisplay()
        task = display.add_task("Preparing editorial evidence")
        for description in descriptions:
            display.update(task, description=description)
    return [record.message for record in caplog.records]


def test_a_counted_stage_logs_a_handful_of_lines_including_start_and_end(caplog):
    lines = _logged(
        caplog,
        [f"Preparing previews: {n}/135 · ~{135 - n}s left in this stage" for n in range(1, 136)],
    )

    counted = [line for line in lines if line.startswith("Preparing previews")]
    assert len(counted) <= 5
    assert counted[0].startswith("Preparing previews: 1/135")
    assert counted[-1].startswith("Preparing previews: 135/135")


def test_every_stage_gets_its_own_start_and_end(caplog):
    lines = _logged(
        caplog,
        [f"Preparing previews: {n}/10" for n in range(1, 11)]
        + [f"Preparing captions: {n}/10" for n in range(1, 11)],
    )

    assert "Preparing previews: 1/10" in lines
    assert "Preparing previews: 10/10" in lines
    assert "Preparing captions: 1/10" in lines
    assert "Preparing captions: 10/10" in lines


def test_lines_without_a_count_still_log_every_change(caplog):
    lines = _logged(caplog, ["Downloading clips", "Assembling", "Mixing music"])

    assert lines[-3:] == ["Downloading clips", "Assembling", "Mixing music"]
