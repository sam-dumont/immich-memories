"""Dated nightly image tags expire; nothing else in the registry ever does."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.prune_nightly_images import expired_versions

TODAY = "20261031"


def version(version_id, *tags):
    return {"id": version_id, "metadata": {"container": {"tags": list(tags)}}}


@pytest.mark.parametrize(
    ("tags", "expired"),
    [
        (["nightly-20261001"], True),
        (["nightly-20261001", "nightly-20261001-cuda"], True),
        (["nightly-20261017"], True),  # 14 days old: past the window
        (["nightly-20261018"], False),  # 13 days old
        # Still the current nightly, or re-dated by a later run: keep.
        (["nightly", "nightly-20261001"], False),
        (["nightly-cuda", "nightly-20261001-cuda"], False),
        (["nightly-20261001", "nightly-20261030"], False),
        # Releases, candidates, latest, commit builds and untagged children: never.
        (["1.0.0", "latest"], False),
        (["1.0.0-rc.8"], False),
        (["1.0.0-rc.8", "nightly-20261001"], False),
        (["sha-abcdef012345"], False),
        ([], False),
    ],
)
def test_only_versions_whose_every_tag_is_an_old_nightly_date_expire(tags, expired):
    assert expired_versions([version(7, *tags)], TODAY, keep_days=14) == ([7] if expired else [])


def test_the_command_prints_the_ids_to_delete():
    pages = [[version(1, "nightly-20260901"), version(2, "1.0.0")], [version(3, "nightly")]]
    result = subprocess.run(
        [sys.executable, "scripts/prune_nightly_images.py", "--today", TODAY],
        input=json.dumps(pages),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["1"]


def test_the_daily_prune_runs_alone_and_never_on_pull_requests():
    workflow = yaml.safe_load(Path(".github/workflows/image-maintenance.yml").read_text())
    crons = [entry["cron"] for entry in workflow[True]["schedule"]]
    daily = next(cron for cron in crons if cron.endswith("* * *"))
    jobs = workflow["jobs"]
    assert f"github.event.schedule != '{daily}'" in jobs["inventory"]["if"]
    assert "github.event_name != 'pull_request'" in jobs["prune-nightly"]["if"]
    assert jobs["prune-nightly"]["permissions"] == {"contents": "read", "packages": "write"}
    assert "github.event.schedule" in workflow["concurrency"]["group"]
