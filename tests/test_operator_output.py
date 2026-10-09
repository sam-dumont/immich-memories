"""Operator output reports real work without requiring a working configuration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from immich_memories.automation.phase_log import log_phase_progress
from immich_memories.cli import main
from immich_memories.generate_progress import clip_preparation_events
from immich_memories.operations.phases import OperationalPhase, PhaseEvent
from tests.test_render_progress_events import _Clock, _Operational


@pytest.fixture(autouse=True)
def restore_logging_after_startup():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    alembic_level = logging.getLogger("alembic").level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    logging.getLogger("alembic").setLevel(alembic_level)


@pytest.mark.parametrize("command", [["generate"], ["ui"], ["auto", "run"], ["store", "facts"]])
def test_subcommand_help_ignores_a_broken_configuration(tmp_path: Path, command: list[str]):
    config = tmp_path / "broken.yaml"
    config.write_text("immich: [invalid\n")
    result = CliRunner().invoke(main, ["--config", str(config), *command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
    assert "invalid" not in result.output


def test_phase_logs_use_the_time_the_child_reported(caplog):
    timestamp = datetime(2026, 1, 1, 3, 0, 5, 125000, tzinfo=UTC)
    event = PhaseEvent(OperationalPhase.RENDER, 3, 10, "Preparing clips", 12, timestamp=timestamp)
    assert event.to_dict()["timestamp"] == timestamp.isoformat()
    with caplog.at_level(logging.INFO), log_phase_progress(lambda: [event.to_dict()]):
        pass
    record = next(record for record in caplog.records if record.name.endswith("phase_log"))
    assert record.created == timestamp.timestamp()
    assert logging.Formatter("%(asctime)s").format(record).endswith(",125")
    assert "3/10" in record.getMessage()


def test_each_prepared_source_updates_the_count_before_the_heartbeat():
    operational, clock = _Operational(), _Clock()
    callback = clip_preparation_events(None, operational, OperationalPhase.RENDER, 10, clock=clock)
    for count in range(11):
        callback("extract", 0.7 * count / 10, "Preparing")
        callback("extract", 0.7 * count / 10, "Preparing")
        clock.now += 1
    assert [event[1] for event in operational.events] == list(range(11))


def test_default_and_explicit_auto_share_one_hardware_probe():
    from immich_memories.processing import hardware_detection as hardware
    from immich_memories.processing.hardware import HWAccelBackend, HWAccelCapabilities

    hardware._cached_hardware_detection.cache_clear()
    caps = HWAccelCapabilities(backend=HWAccelBackend.NVIDIA, supports_h264_encode=True)
    try:
        # WHY: the hardware detector probes FFmpeg and the physical GPU.
        with patch.object(hardware, "_detect_nvidia", return_value=caps) as probe:
            assert hardware.detect_hardware_acceleration() is caps
            assert hardware.detect_hardware_acceleration("auto") is caps
            assert hardware.detect_hardware_acceleration(backend="auto") is caps
        assert probe.call_count == 1
    finally:
        hardware._cached_hardware_detection.cache_clear()


def test_unconfigured_home_is_an_optional_feature():
    from immich_memories.config import Config
    from immich_memories.preflight import CheckStatus
    from immich_memories.preflight_homebase import check_homebase

    result = check_homebase(Config())
    assert result.status is CheckStatus.SKIPPED
    assert "trips and seasons" in result.message


@pytest.mark.parametrize("level, expected", [("INFO", False), ("DEBUG", True)])
def test_ui_access_log_is_enabled_only_for_verbose_runs(monkeypatch, level, expected):
    from immich_memories.config import Config
    from immich_memories.web import server
    from tests.web_server_fixtures import SESSION_SECRET

    assert Path.home().parent.name.startswith("immich-memories-pytest-")
    # WHY: configuration and the listening server are external boundaries; startup stays real.
    monkeypatch.setattr(server, "get_config", lambda: Config())
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", SESSION_SECRET)
    with patch("uvicorn.run") as run:
        server.main(port=0, log_level=level)
    assert run.call_args.kwargs.get("access_log") is expected


def test_a_taken_ui_port_suggests_a_different_port(monkeypatch, capsys):
    import socket

    from immich_memories.config import Config
    from immich_memories.web import server
    from tests.web_server_fixtures import SESSION_SECRET

    assert Path.home().parent.name.startswith("immich-memories-pytest-")
    # WHY: load only this test's configuration; exercise a real occupied listening socket.
    monkeypatch.setattr(server, "get_config", lambda: Config())
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", SESSION_SECRET)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(SystemExit):
            server.main(port=listener.getsockname()[1])
    output = capsys.readouterr().err
    assert "immich-memories ui --port <free>" in output
    assert "kill" not in output


def test_startup_without_home_skips_trip_refreshes(caplog):
    from immich_memories.config import Config
    from immich_memories.web.server import _warm_answers

    assert Path.home().parent.name.startswith("immich-memories-pytest-")
    config = Config(immich={"url": "https://immich.example.com", "api_key": "test-key"})
    # WHY: suggestion and trip refreshes would query Immich on background threads.
    with (
        patch("immich_memories.web.suggestions.suggestions_answer") as suggestions,
        patch("immich_memories.web.library.trips_answer") as trips,
        caplog.at_level(logging.INFO),
    ):
        _warm_answers(config)
    assert suggestions.call_count == 1
    assert not trips.called
    assert "Trip suggestions are off until home coordinates are configured" in caplog.text
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_pipeline_timing_labels_source_work_as_preparation(caplog):
    from immich_memories.generate import _log_phase_timing

    with caplog.at_level(logging.INFO):
        _log_phase_timing({"prepare": 12, "assembly": 6, "music": 2, "total": 20}, 4)
    assert "prepare=12.0s (60%)" in caplog.text
    assert "download=" not in caplog.text
