"""Display a saved-cut render whether or not a browser sidecar was requested."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from immich_memories.cli._helpers import console
from immich_memories.cli._live_display import LiveDisplay, QuietDisplay
from immich_memories.cli.progress_file import progress_writer
from immich_memories.tracking.timing import active


@contextmanager
def render_progress(
    path: Path | None,
    *,
    interactive: bool | None = None,
) -> Iterator[Callable[[str, float, str], None]]:
    """Send the same forecast to the terminal and optional saved job record."""
    interactive = console.is_terminal if interactive is None else interactive
    writer = progress_writer(path)
    with LiveDisplay(console) if interactive else QuietDisplay() as display:
        task = display.add_task("Preparing the saved cut", total=None)

        def report(phase: str, fraction: float, message: str) -> None:
            if writer:
                writer(phase, fraction, message)
            collected = active()
            progress = collected.diagnostics.get("progress", {}) if collected else {}
            display.update(task, description=message, forecast=progress.get("forecast"))
            if phase == "done":
                display.update(task, completed=True)

        yield report
