"""Starting the server settles the runs a dead process left `running`."""

from datetime import UTC, datetime

from starlette.testclient import TestClient

from immich_memories.config import get_config, load_config, set_config
from immich_memories.db import open_store
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase
from immich_memories.web.server import create_app


def test_a_run_left_running_by_a_restart_shows_under_interrupted(tmp_path):
    # This test is about the restart sweep, not sign-in.
    path = tmp_path / "config.yaml"
    path.write_text("auth:\n  enabled: false\n")
    load_config(path)
    try:
        db = RunDatabase(open_store(get_config()))
        db.save_run(RunMetadata(run_id="killed", created_at=datetime.now(tz=UTC), status="running"))

        with TestClient(create_app()) as client:
            listed = client.get("/api/v1/runs", params={"status": "interrupted"}).json()
    finally:
        set_config(None)

    assert [run["run_id"] for run in listed["runs"]] == ["killed"]
