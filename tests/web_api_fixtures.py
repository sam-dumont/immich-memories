"""A saved cut on disk and an API client over it, for the /api/v1 tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from immich_memories.analysis.editorial_contracts import (
    DecisionProvenance,
    PassTrace,
    TraceDecision,
)
from immich_memories.analysis.selection_trace import Trace
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.operations.run_index import record_run_attempt
from immich_memories.operations.storyboard import PLAN_FILE, PROJECTION_FILE, TRACE_FILE
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import RunMetadata
from immich_memories.web import mount_web
from immich_memories.web.dependencies import current_config

PLAN: dict[str, Any] = {
    "story": {
        "thesis": "A month that ends by the lake.",
        "episodes": [
            {"episode": "garden", "title": "Lunch in the garden"},
            {"episode": "lake", "title": "Two nights by the lake"},
        ],
    },
    "carriers": [
        {
            "asset_id": "lake-1",
            "taken": "2024-06-21T18:45:00",
            "story_episode": "lake",
            "kind": "video",
            "seconds": 4.0,
            "why": "Two nights by the lake: the tents on the slope",
            "depicted_moment": "m-lake",
        },
        {
            "asset_id": "garden-1",
            "taken": "2024-06-08T12:15:00",
            "story_episode": "garden",
            "kind": "photo",
            "seconds": 4.0,
            "why": "Lunch in the garden: the table still out",
            "depicted_moment": "m-garden",
            "moment_alternatives": ["woods-9", "garden-3"],
        },
    ],
}


def config_in(tmp_path: Path) -> Config:
    config = Config()
    config.cache.directory = str(tmp_path / "cache")
    config.cache.database = str(tmp_path / "cache" / "runs.db")
    return config


def api_client(config: Config) -> TestClient:
    app = FastAPI()
    mount_web(app)
    app.dependency_overrides[current_config] = lambda: config
    return TestClient(app)


def selection_trace() -> Trace:
    """garden-1 passes the picture review; woods-9 is left out there as a near duplicate."""
    trace = Trace()
    trace.clips = {"garden-1": "photo, 2024-06-08", "woods-9": "photo, 2024-06-15"}
    trace.editorial_passes.append(
        PassTrace(
            name="picture-review",
            input_ids=("garden-1", "lake-1", "woods-9"),
            kept_ids=("garden-1", "lake-1"),
            rejected=(TraceDecision("woods-9", "a near duplicate of the path shot"),),
            unresolved=(),
            duration_before=12.0,
            duration_after=8.0,
            provenance=DecisionProvenance(
                pass_name="picture-review",  # noqa: S106 - a pass label, not a secret
                pass_version="1",  # noqa: S106 - a version label, not a secret
                schema_version="1",
                model_identity="rules",
                input_ids=(),
                sheet_hashes=(),
                request_key="",
                cache_hit=False,
            ),
        )
    )
    return trace


def save_run(
    config: Config,
    run_id: str,
    *,
    when: datetime = datetime(2026, 9, 13, 8, tzinfo=UTC),
    cut: bool = True,
    trace: Trace | None = None,
    polish: dict | None = None,
    **fields: Any,
) -> Path | None:
    """A run in the database and, with `cut`, the attempt directory its storyboard reads."""
    RunDatabase(open_store(config)).save_run(
        RunMetadata(
            run_id=run_id,
            created_at=when,
            status=fields.pop("status", "completed"),
            memory_type=fields.pop("memory_type", "monthly_highlights"),
            **fields,
        )
    )
    if not cut:
        return None
    attempt = config.cache.cache_path / "editorial-runs" / run_id / "attempts" / "a1"
    attempt.mkdir(parents=True)
    (attempt / PLAN_FILE).write_text(json.dumps(PLAN))
    (attempt / PROJECTION_FILE).write_text(json.dumps({"intervals": {"lake-1": [12.5, 16.5]}}))
    if trace is not None:
        (attempt / TRACE_FILE).write_text(json.dumps(trace.as_dict()))
    if polish is not None:
        (attempt / "derived-decisions").mkdir()
        (attempt / "derived-decisions" / "thin-polish.private.json").write_text(json.dumps(polish))
    record_run_attempt(run_id, attempt, attempt / "film.mp4", store=open_store(config))
    return attempt
