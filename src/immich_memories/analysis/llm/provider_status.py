"""Say that the reader stopped answering, the moment it stops.

The retry in `llm.query` is right and stays: one dropped connection once
killed a 26-minute run. What was missing is that nobody was told. Until this
module, a reader that went away meant six silent seconds and then a dead run,
with nothing said on either surface.

The stage names the reader, never its server: progress text carries no config value.
"""

from __future__ import annotations

from collections.abc import Callable

from immich_memories.analysis.llm.wire import TRANSPORT_RETRIES, LLMTransportAttempt
from immich_memories.operations.cut_progress import StageUpdate, announce_stage
from immich_memories.progress_text import Stage


def watch_provider() -> Callable[[LLMTransportAttempt], None]:
    """A transport observer that announces each dropped connection as a stage."""

    def observe(attempt: LLMTransportAttempt) -> None:
        if attempt.outcome != "connection_error":
            return
        if attempt.attempt >= TRANSPORT_RETRIES:
            # Most callers now go on without it (the film falls back to the rules), so this
            # says to check the server and promises nothing about the run.
            announce_stage(
                StageUpdate(Stage.CUT_READER_GAVE_UP, params={"retries": TRANSPORT_RETRIES})
            )
            return
        announce_stage(
            StageUpdate(
                Stage.CUT_READER_WAITING,
                params={"attempt": attempt.attempt, "retries": TRANSPORT_RETRIES},
            )
        )

    return observe
