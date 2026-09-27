"""Required hermetic browser smoke for the launch-critical generation path."""

from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml
from playwright.sync_api import Page, expect

from immich_memories.processing.encoding_plan import (
    EncodingPlan,
    HdrTransfer,
    OutputCodec,
)
from immich_memories.processing.output_contract import (
    InvalidOutputArtifact,
    OutputProbe,
    validate_output,
)
from immich_memories.tracking.run_database import RunDatabase
from tests.e2e.conftest import _build_launch_environment
from tests.e2e.web_flow import cut_june, films, render, the_film

pytestmark = pytest.mark.e2e


def test_launch_environment_strips_all_production_shortcuts(monkeypatch) -> None:
    """Personal provider settings must never escape into the fake-service app."""
    shortcut_names = {
        "IMMICH_URL",
        "IMMICH_API_KEY",
        "OPENAI_API_KEY",
        "MUSICGEN_ENABLED",
        "MUSICGEN_BASE_URL",
        "MUSICGEN_API_KEY",
        "ACE_STEP_ENABLED",
        "ACE_STEP_MODE",
        "ACE_STEP_API_URL",
    }
    for name in shortcut_names:
        monkeypatch.setenv(name, "https://personal.example.invalid/secret")

    environment = _build_launch_environment()

    assert shortcut_names.isdisjoint(environment)


def test_failed_output_validation_records_sanitized_probe_without_removing_video(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Failed validation must leave CI a safe probe and the original video."""
    output_path = tmp_path / "memory.mp4"
    output_path.write_bytes(b"rendered-video")
    diagnostic_path = tmp_path / "output-probe.json"

    def fail_validation(path: Path, plan: EncodingPlan) -> None:
        raise InvalidOutputArtifact(f"invalid output at {path}")

    monkeypatch.setattr(
        "tests.e2e.test_launch_smoke.validate_output",
        fail_validation,
    )

    with pytest.raises(InvalidOutputArtifact, match="invalid output"):
        _validate_and_record_output(  # type: ignore[name-defined,arg-type]
            output_path,
            None,
            diagnostic_path,
        )

    assert output_path.read_bytes() == b"rendered-video"
    assert diagnostic_path.exists()
    assert json.loads(diagnostic_path.read_text()) == {
        "output": {
            "exists": True,
            "size_bytes": len(b"rendered-video"),
        },
        "validation": {
            "error_type": "InvalidOutputArtifact",
            "status": "failed",
        },
    }


def test_successful_output_validation_records_sanitized_probe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Successful validation must leave CI the normalized output evidence."""
    output_path = tmp_path / "memory.mp4"
    output_path.write_bytes(b"rendered-video")
    diagnostic_path = tmp_path / "output-probe.json"
    probe = OutputProbe(
        codec="h264",
        container="mp4",
        duration_seconds=1.25,
        size_bytes=len(b"rendered-video"),
        pixel_format="yuv420p",
        color_transfer="bt709",
        color_primaries="bt709",
        width=1280,
        height=720,
        decoded_frames=30,
    )

    monkeypatch.setattr(
        "tests.e2e.test_launch_smoke.validate_output",
        lambda _path, _plan: probe,
    )

    assert _validate_and_record_output(output_path, None, diagnostic_path) is probe  # type: ignore[arg-type]
    assert diagnostic_path.exists()
    assert json.loads(diagnostic_path.read_text()) == {
        "output": {
            "exists": True,
            "size_bytes": len(b"rendered-video"),
        },
        "probe": asdict(probe),
        "validation": {"status": "passed"},
    }


def _output_diagnostic(path: Path) -> dict[str, bool | int | None]:
    """Return only non-sensitive facts about the generated output."""
    exists = path.is_file()
    return {
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
    }


def _write_output_diagnostic(path: Path, diagnostic: dict[str, object]) -> None:
    """Persist deterministic, non-sensitive E2E artifact metadata."""
    path.write_text(json.dumps(diagnostic, indent=2, sort_keys=True))


def _validate_and_record_output(
    output_path: Path,
    plan: EncodingPlan,
    diagnostic_path: Path,
) -> OutputProbe:
    """Validate one E2E artifact while always preserving failure diagnostics."""
    try:
        probe = validate_output(output_path, plan)
    except Exception as exc:
        _write_output_diagnostic(
            diagnostic_path,
            {
                "output": _output_diagnostic(output_path),
                "validation": {
                    "error_type": type(exc).__name__,
                    "status": "failed",
                },
            },
        )
        raise
    _write_output_diagnostic(
        diagnostic_path,
        {
            "output": _output_diagnostic(output_path),
            "probe": asdict(probe),
            "validation": {"status": "passed"},
        },
    )
    return probe


def test_launch_flow_renders_real_video(
    page: Page,
    launch_app_url: str,
    launch_workspace,
) -> None:
    """The default monthly flow, cut then rendered in the browser, must publish one real H.264 video."""
    page.goto(launch_app_url, wait_until="domcontentloaded", timeout=30_000)
    readiness = page.request.get(f"{launch_app_url}/health/ready")
    assert readiness.status == 200
    assert readiness.json()["immich"] == {
        "status": "ready",
        "reachable": True,
        "api_version_policy": "auto",
        "resolved_api_version": "v3",
    }
    launch_config = yaml.safe_load(launch_workspace.config_path.read_text())
    assert launch_config["advanced"]["hardware"]["enabled"] is False
    assert launch_config["advanced"]["musicgen"]["enabled"] is False
    assert launch_config["advanced"]["ace_step"]["enabled"] is False

    before = set(launch_workspace.output_dir.rglob("*.mp4"))
    cut_june(page, launch_app_url)
    page.evaluate("""() => {
        window.exportProgress = [];
        new MutationObserver(() => {
            const bar = document.querySelector('[role="progressbar"]');
            if (bar) window.exportProgress.push(Number(bar.getAttribute('aria-valuenow')));
        }).observe(document.body, {subtree: true, childList: true, attributes: true,
                                   attributeFilter: ['aria-valuenow']});
    }""")
    render(page, resolution="720p")

    expect(the_film(page)).to_be_visible(timeout=600_000)
    fractions = page.evaluate("window.exportProgress")
    assert len(set(fractions)) > 2
    assert fractions == sorted(fractions)

    outputs = sorted(set(launch_workspace.output_dir.rglob("*.mp4")) - before)
    assert len(outputs) == 1
    output_path = outputs[0]
    plan = EncodingPlan(
        codec=OutputCodec.H264,
        encoder="libx264",
        encoder_args=(),
        target_transfer=HdrTransfer.NONE,
        tone_map_to_sdr=False,
        pixel_format="yuv420p",
        container="mp4",
    )
    probe = _validate_and_record_output(
        output_path,
        plan,
        launch_workspace.root / "output-probe.json",
    )
    assert probe.codec == "h264"
    assert (probe.width, probe.height) == (1280, 720)
    assert probe.duration_seconds > 0
    assert probe.size_bytes > 0

    database = RunDatabase(launch_workspace.database_path)
    rendered = films(database)[0]
    assert Path(rendered.output_path or "") == output_path
    assert rendered.source == "manual"
    assert database.list_runs(status="running") == []
    _verify_cli_timing(launch_workspace, database)


def _verify_cli_timing(workspace, database: RunDatabase) -> None:
    """Run the same June cut through the terminal and retain its durable timing evidence."""
    from tests.e2e.cli_bootstrap import CLI_BOOTSTRAP

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            str(root / ".venv/bin/python"),
            "-c",
            CLI_BOOTSTRAP,
            str(workspace.config_path),
            str(workspace.root / "state"),
            "generate",
            "--memory-type",
            "monthly_highlights",
            "--year",
            "2024",
            "--month",
            "6",
            "--no-music",
            "--quiet",
        ],
        cwd=root,
        env=_build_launch_environment(workspace.root),
        capture_output=True,
        text=True,
        timeout=600,
    )
    transcript = result.stdout + result.stderr
    evidence = root / "test-results"
    evidence.mkdir(exist_ok=True)
    (evidence / "phase-timing-cli.txt").write_text(
        transcript.replace(str(workspace.root), "<fixture-workspace>")
    )
    assert result.returncode == 0, transcript
    terminal = database.list_runs(status="completed", order_by_completion=True)[0]
    assert terminal.output_path and Path(terminal.output_path).is_file()
    assert any(event["elapsed_seconds"] > 0 for event in terminal.phase_events)
    assert terminal.phase_events[-1]["phase"] == "complete"


def test_reload_during_a_render_rejoins_it_and_plays_the_film(
    page: Page,
    launch_app_url: str,
    launch_workspace,
) -> None:
    """A reload mid-render must come back to the running job, then the film (#322)."""
    before = set(launch_workspace.output_dir.rglob("*.mp4"))
    cut_june(page, launch_app_url)
    render(page, resolution="720p")
    panel = page.get_by_role("region", name="Render")
    expect(panel.get_by_role("region", name="Progress")).to_be_visible(timeout=30_000)

    # WHY: a reload is what a user does when the progress bar seems stuck.
    page.reload(wait_until="domcontentloaded", timeout=30_000)

    expect(panel.get_by_role("region", name="Progress")).to_be_visible(timeout=30_000)
    expect(the_film(page)).to_be_visible(timeout=600_000)

    outputs = set(launch_workspace.output_dir.rglob("*.mp4")) - before
    assert len(outputs) == 1
    database = RunDatabase(launch_workspace.database_path)
    assert Path(films(database)[0].output_path or "") == outputs.pop()


def test_a_typed_url_never_receives_the_stored_key(page: Page, launch_app_url: str) -> None:
    """#1212: the stored key only goes to the URL it was stored for."""
    seen: list[str | None] = []

    class Listener(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            seen.append(self.headers.get("x-api-key"))
            self.send_response(404)
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            return

    listener = HTTPServer(("127.0.0.1", 0), Listener)
    threading.Thread(target=listener.serve_forever, daemon=True).start()
    try:
        page.goto(f"{launch_app_url}/app/settings", wait_until="domcontentloaded", timeout=30_000)
        expect(page.get_by_label("Immich Server URL")).to_have_value(re.compile(r"^http"))
        page.get_by_label("Immich Server URL").fill(f"http://127.0.0.1:{listener.server_port}")
        page.get_by_role("button", name="Test Connection").click()

        expect(page.get_by_text("enter the API key for the new server")).to_be_visible()
        assert seen == []
    finally:
        listener.shutdown()
