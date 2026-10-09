"""The browser shows a terminal job error even when no output log is available."""

import json
import time

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_full_storage_ends_progress_and_shows_recovery_without_a_log(page, launch_app_url):
    job = {
        "id": "a" * 32,
        "kind": "cut",
        "argv": [],
        "status": "running",
        "started_at": time.time(),
        "command": "immich-memories generate --no-render",
        "progress": {"label": "Preparing the pool", "recent_asset_ids": []},
    }
    message = "Storage is full. Expand the cache volume, then retry."
    failed = {**job, "status": "failed", "exit_code": 1, "error": message}
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # WHY: the API boundary supplies a failed job whose disk could not retain its log.
    page.route("**/api/v1/jobs/active", lambda route: route.fulfill(json=job))
    page.route(
        f"**/api/v1/jobs/{job['id']}/events",
        lambda route: route.fulfill(
            body=f"data: {json.dumps(failed)}\n\n", content_type="text/event-stream"
        ),
    )
    page.route(f"**/api/v1/jobs/{job['id']}/output", lambda route: route.abort())
    page.goto(f"{launch_app_url}/app/create")

    panel = page.get_by_role("region", name="Progress")
    expect(panel.get_by_text("It did not finish.")).to_be_visible()
    expect(panel.get_by_role("alert")).to_have_text(message)
    expect(panel.get_by_role("progressbar")).to_have_count(0)
    expect(panel.get_by_role("button", name="Cancel")).to_have_count(0)
    assert errors == []
