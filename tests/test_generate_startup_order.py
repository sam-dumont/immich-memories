"""A failed Immich connection reaches the operator before local GPU setup."""

from unittest.mock import create_autospec

from click.testing import CliRunner

from immich_memories.api.immich import ImmichAPIError, SyncImmichClient
from immich_memories.cli import main
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.tracking.run_database import RunDatabase


def test_unreachable_immich_fails_without_capturing_hardware(tmp_path, monkeypatch):
    config = Config(
        immich={"url": "http://immich.test", "api_key": "test-key"},
        output={"directory": str(tmp_path)},
    )
    # WHY: the client boundary fails before any media or local hardware is needed.
    client = create_autospec(SyncImmichClient, instance=True)
    client.require_read_permissions.side_effect = ImmichAPIError("Immich is unavailable")
    monkeypatch.setattr("immich_memories.api.immich.SyncImmichClient", lambda **_kwargs: client)
    # WHY: configuration comes from this sealed test, never the operator's home.
    monkeypatch.setattr("immich_memories.cli.get_config", lambda: config)

    def never_probe():
        raise AssertionError("hardware was probed before connecting to Immich")

    # WHY: hardware detection can compile native code and is the ordering boundary.
    monkeypatch.setattr("immich_memories.tracking.run_tracker.capture_system_info", never_probe)
    result = CliRunner().invoke(main, ["generate", "--year", "2024", "--no-render"])
    assert result.exit_code != 0
    assert "Immich is unavailable" in result.output
    assert "hardware was probed" not in str(result.exception)
    run = RunDatabase(open_store(config)).list_runs(limit=1)[0]
    assert run.status == "failed"
    assert run.system_info is None


def test_diagnostics_captured_after_connection_are_saved_once(monkeypatch):
    from immich_memories.tracking.models import SystemInfo
    from immich_memories.tracking.run_observations import observe_run

    config = Config()
    store = open_store(config)
    captures = []
    info = SystemInfo("linux", "test", "3.12", "x86_64", cpu_cores=4)

    def capture():
        captures.append(info)
        return info

    # WHY: native hardware detection is external; run ownership and storage stay real.
    monkeypatch.setattr("immich_memories.tracking.run_tracker.capture_system_info", capture)
    with observe_run(store, source="manual", capture_system=False) as tracker:
        assert not captures
        tracker.record_system_info()
        tracker.record_system_info()

    saved = RunDatabase(store).get_run(tracker.run_id)
    assert saved is not None
    assert saved.system_info == info
    assert len(captures) == 1
