"""Refused pipeline-run lifecycle transitions and the state that explains them."""

from __future__ import annotations

from typing import NoReturn

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.db.tables import pipeline_runs


class InvalidRunLifecycleError(RuntimeError):
    """Raised when a run's lifecycle state forbids a requested transition."""


class DuplicateRunError(RuntimeError):
    """Raised when a new tracker tries to claim an existing run identity."""


def _state(connection: Connection, run_id: str) -> sa.Row:
    row = connection.execute(
        sa.select(pipeline_runs.c.status, pipeline_runs.c.delivery_status).where(
            pipeline_runs.c.run_id == run_id
        )
    ).first()
    if row is None:
        raise KeyError(f"Unknown pipeline run: {run_id}")
    return row


def raise_invalid_delivery_transition(connection: Connection, run_id: str) -> NoReturn:
    """Re-read the run to name which precondition the delivery transition missed."""
    status, delivery_status = _state(connection, run_id)
    if status == "completed":
        raise InvalidRunLifecycleError(
            f"Delivery transition requires requested delivery; run '{run_id}' is "
            f"'{delivery_status}'"
        )
    raise InvalidRunLifecycleError(
        f"Delivery transition requires a completed run; run '{run_id}' is '{status}'"
    )


def raise_invalid_artifact_transition(connection: Connection, run_id: str) -> NoReturn:
    """Re-read the run to name the status that blocked artifact completion."""
    status, _ = _state(connection, run_id)
    raise InvalidRunLifecycleError(
        f"Artifact completion requires a running run; run '{run_id}' is '{status}'"
    )
