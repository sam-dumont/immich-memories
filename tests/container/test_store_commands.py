"""`store backup` and `store restore` inside the image, with its own database clients."""

from __future__ import annotations

import json

import pytest

from tests.container.deployment import parse_counts

pytestmark = [pytest.mark.container]


def test_a_backup_restores_into_a_scratch_store_with_every_count_equal(deployment, upgraded):
    # On PostgreSQL this is the image's pg_dump and pg_restore against a postgres:16
    # server: a client the server refuses shows up here, not in a user's restore.
    backup = "/tmp/container-e2e." + ("dump" if deployment.postgres else "db")
    scratch = deployment.scratch_store()
    before = parse_counts(deployment.cli("store", "status"))

    deployment.cli("store", "backup", "--to", backup)
    manifest = json.loads(deployment.shell(f"cat {backup}.manifest.json"))
    deployment.cli("store", "restore", "--from", backup, "--force", env=scratch)
    restored = parse_counts(deployment.cli("store", "status", env=scratch))

    assert sum(before.values()) > 0
    assert manifest["counts"] == before
    assert restored == before
