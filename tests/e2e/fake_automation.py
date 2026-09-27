"""Keep automation discovery and its real CLI child inside the fixture library."""

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from immich_memories.automation.models import ProcessResult

# A test drops this file to make the next child fail the way a real generation
# fails: its run record already opened, then a non-zero exit.
FAIL_MARKER = "fail-next-child"


class FixtureDate(date):
    @classmethod
    def today(cls):
        return cls(2024, 7, 1)


def _child_that_opened_its_run_then_failed(command: list[str]) -> ProcessResult:
    from immich_memories.config import get_config
    from immich_memories.tracking import RunDatabase
    from immich_memories.tracking.models import RunMetadata

    values = dict(arg.split("=", 1) for arg in command if arg.startswith("--") and "=" in arg)
    RunDatabase(get_config().cache.database_path).save_run(
        RunMetadata(
            run_id="fixture-failed-child",
            created_at=datetime.now(),
            status="failed",
            source="auto",
            memory_key=values.get("--memory-key"),
            automation_attempt_id=values["--automation-attempt-id"],
            warnings=["The fixture provider refused the render"],
        )
    )
    return ProcessResult(1, "starting the fixture render\n", "the fixture provider refused\n")


def install_fake_automation(config_path: Path, state_dir: Path) -> None:
    """Use a fixed calendar and fixture geocoder; only the editorial model is scripted."""
    from immich_memories.analysis import trip_detection
    from immich_memories.automation import candidate_discovery, runner
    from tests.e2e.cli_bootstrap import CLI_BOOTSTRAP

    candidate_discovery.date = FixtureDate
    # WHY: naming the fixture's lake must not contact the public Nominatim service.
    trip_detection.reverse_geocode = lambda *_args, **_kwargs: "Annecy, France"

    def execute(command):
        marker = state_dir / FAIL_MARKER
        if marker.is_file():
            marker.unlink()
            return _child_that_opened_its_run_then_failed(command)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                CLI_BOOTSTRAP,
                str(config_path),
                str(state_dir),
                *command[1:],
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        return ProcessResult(result.returncode, result.stdout, result.stderr)

    # WHY: keep the real generate command and rendering, while installing the fixture editor in its child.
    runner._execute_generate = execute


def install_hermetic_web_jobs(
    app, config_path: Path, state_dir: Path, bootstrap: str | None = None
) -> None:
    """The web client's cut and render children run the real CLI with the fixture editor.

    The same bootstrap the automation child uses, behind the `cli_executable` seam: the job
    still runs the command the page shows, only the editorial model is scripted. A test that
    scripts one more remote service passes its own `bootstrap`, which takes the same argv.
    """
    from immich_memories.web.job_routes import cli_executable
    from tests.e2e.cli_bootstrap import CLI_BOOTSTRAP

    bootstrap = bootstrap or CLI_BOOTSTRAP

    launcher = state_dir / "hermetic-immich-memories"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        f"os.execv(sys.executable, [sys.executable, '-c', {bootstrap!r}, "
        f"{str(config_path)!r}, {str(state_dir)!r}, *sys.argv[1:]])\n"
    )
    launcher.chmod(0o755)
    # WHY: the child must carry the fixture editor; the server's own patch does not cross a fork.
    app.dependency_overrides[cli_executable] = lambda: str(launcher)
