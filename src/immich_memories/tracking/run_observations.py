"""Run ownership begins before discovery, so failed cuts and preparation have history."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from functools import wraps

from immich_memories.analysis import llm_metrics
from immich_memories.db import Store, open_store
from immich_memories.operations.cancellation import PipelineCancelled
from immich_memories.tracking import timing
from immich_memories.tracking.run_database import RunDatabase
from immich_memories.tracking.run_tracker import RunTracker
from immich_memories.tracking.span_store import SpanStore

_tracker: ContextVar[RunTracker | None] = ContextVar("observed_run", default=None)


def current_tracker() -> RunTracker | None:
    """Let render reuse the run that already paid for discovery and selection."""
    return _tracker.get()


@contextmanager
def observe_run(
    store: Store,
    *,
    source: str,
    memory_type: str | None = None,
    capture_system: bool = True,
) -> Iterator[RunTracker]:
    """Save buffered work on success, cancellation, or failure, then reset context."""
    tracker = RunTracker(store=store, capture_system=capture_system)
    tracker.start_run(source=source, memory_type=memory_type)
    token = _tracker.set(tracker)
    with (
        ExitStack() as cleanup,
        timing.collecting() as collected,
        llm_metrics.collecting() as counters,
    ):
        cleanup.callback(_tracker.reset, token)
        try:
            with timing.span("run"):
                yield tracker
        except (PipelineCancelled, KeyboardInterrupt):
            if _still_running(tracker):
                tracker.cancel_run()
            raise
        except SystemExit as error:
            if _still_running(tracker):
                _end_on_exit(tracker, error)
            raise
        except BaseException as error:
            tracker.fail_run(str(error))
            raise
        else:
            if _still_running(tracker):
                tracker.complete_run()
        finally:
            _save_observations(tracker.db, tracker.run_id, collected, counters)


def _still_running(tracker: RunTracker) -> bool:
    saved = tracker.db.get_run(tracker.run_id)
    return saved is not None and saved.status == "running"


def _end_on_exit(tracker: RunTracker, error: SystemExit) -> None:
    # "Nothing worth a film" exits 0 after finishing the run's work.
    if timing.clean_exit(error):
        tracker.complete_run()
    else:
        tracker.fail_run(f"Exited with status {error.code}")


@contextmanager
def observe_render(config) -> Iterator[None]:
    """Collect around a direct render without taking ownership of its run lifecycle.

    The generator validates inputs before starting its run. A CLI-owned run already
    has a buffer; a direct render binds this buffer when RunTracker starts it.
    """
    if timing.active() is not None:
        yield
        return
    from immich_memories.tracking.report_context import record_config

    with timing.collecting() as collected, llm_metrics.collecting() as counters:
        record_config(config, {})
        try:
            with timing.span("run"):
                yield
        finally:
            if collected.run_id is not None:
                _save_observations(
                    RunDatabase(open_store(config)), collected.run_id, collected, counters
                )


def _save_observations(
    database: RunDatabase,
    run_id: str,
    collected: timing.Collector,
    counters: llm_metrics.LLMCounters,
) -> None:
    saved = database.get_run(run_id)
    if saved is None:
        return
    warnings = [warning for measured in collected.spans for warning in measured.warnings]
    database.update_run_status(
        run_id, saved.status, warnings=list(dict.fromkeys([*saved.warnings, *warnings]))
    )
    database.record_llm_metrics(run_id, counters.as_metrics())
    SpanStore(database.store).save(
        run_id,
        collected,
        **collected.diagnostics,
        private_terms=sorted(collected.private_terms),
        private_ids=sorted(collected.private_ids),
        llm={
            **{key.removeprefix("llm_"): value for key, value in counters.as_metrics().items()},
            "by_model": {name: asdict(spend) for name, spend in counters.by_model.items()},
            "by_stage": {name: asdict(spend) for name, spend in counters.by_stage.items()},
        },
    )
    _export_timings(database.store, run_id, collected)


def _export_timings(store: Store, run_id: str, collected: timing.Collector) -> None:
    import json
    import logging

    from immich_memories.operations.run_index import attempt_dir_for_run
    from immich_memories.security import write_secret_file

    attempt = attempt_dir_for_run(run_id, store=store)
    if attempt is None:
        return
    try:
        write_secret_file(
            attempt / "timings.private.json",
            json.dumps(
                [span.to_dict() for span in sorted(collected.spans, key=lambda item: item.span_id)]
            ),
        )
    except OSError:
        logging.getLogger(__name__).warning("Could not mirror timings into the attempt directory")


def observed_command(source: str):
    """Wrap a Click command after its context has resolved the configured store."""

    def decorate(command):
        @wraps(command)
        def observed(ctx, *args, **kwargs):
            if current_tracker() is not None or kwargs.get("dry_run"):
                return command(ctx, *args, **kwargs)
            with observe_run(
                open_store(ctx.obj["config"]),
                source=kwargs.get("source") or source,
                memory_type=kwargs.get("memory_type"),
            ):
                from immich_memories.tracking.report_context import record_config

                record_config(ctx.obj["config"], kwargs)
                return command(ctx, *args, **kwargs)

        return observed

    return decorate
