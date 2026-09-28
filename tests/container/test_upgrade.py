"""An upgrade: the new image starts on a volume the pre-store app wrote, and imports it."""

from __future__ import annotations

import pytest

from tests.container.deployment import APP_HOME, parse_counts

pytestmark = [pytest.mark.container]


def test_the_first_start_imports_the_legacy_volume_into_the_configured_store(deployment, upgraded):
    assert f"Backend:   {deployment.backend}" in upgraded
    assert f"Import:    from {APP_HOME} at " in upgraded
    assert "(at head)" in upgraded
    counts = parse_counts(upgraded)
    for table in ("people", "asset_flags", "pipeline_runs", "automation_attempts", "owner_edits"):
        assert counts.get(table, 0) > 0, (table, counts)


def test_store_import_verify_finds_every_legacy_record(deployment, upgraded):
    verified = deployment.cli("store", "import", "--verify")

    assert "Every legacy record is in the store" in verified
