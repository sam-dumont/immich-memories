"""Playwright E2E test fixtures.

Run locally with: make e2e  (or make screenshots for screenshot capture only)
Requires either a running UI server on :8099 or auto-starts one.

When auto-starting, auth is disabled via IMMICH_MEMORIES_AUTH__ENABLED=false
and the server runs under `coverage run` so UI code coverage is tracked.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import yaml
from playwright.sync_api import Page

from immich_memories.db import Store, StoreLocation, close_stores, open_store
from immich_memories.db.bootstrap import DEFAULT_SCHEMA, normalize_url
from tests.e2e.fake_immich import FakeImmichServer
from tests.store.backends import drop_schema

_BASE_PORT = 8099
_BASE_URL = f"http://localhost:{_BASE_PORT}"
_STARTUP_TIMEOUT = 30  # seconds
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVER_COVERAGE_FILE = _REPO_ROOT / ".coverage.e2e-server"

# The launch check's store backend. Unset: a SQLite file per workspace. A PostgreSQL URL:
# each workspace gets its own schema in that database, dropped when the session ends.
E2E_DATABASE_ENV = "IMMICH_MEMORIES_E2E_DATABASE_URL"


def pytest_configure(config: pytest.Config) -> None:
    """Register the opt-in marker owned by browser artifact tests."""
    config.addinivalue_line(
        "markers",
        "visual: optional screenshots or external-library browser flows",
    )


@dataclass(frozen=True, slots=True)
class LaunchWorkspace:
    """All disposable state owned by the required launch smoke."""

    def store(self) -> Store:
        """The store the launched server records runs in, opened from the test process."""
        return open_store(location=StoreLocation(url=self.store_url, schema=self.store_schema))

    root: Path
    config_path: Path
    database_path: Path
    store_url: str
    store_schema: str
    cache_dir: Path
    output_dir: Path
    log_path: Path


@pytest.fixture(scope="session")
def launch_workspace(
    tmp_path_factory: pytest.TempPathFactory,
    fake_immich_server: FakeImmichServer,
) -> Generator[LaunchWorkspace]:
    """Create one config whose mutable paths stay under a pytest temp root."""
    yield from _owned_workspace(tmp_path_factory.mktemp("launch-smoke"), fake_immich_server)


def _owned_workspace(
    root: Path, fake_immich_server: FakeImmichServer
) -> Generator[LaunchWorkspace]:
    """A workspace whose PostgreSQL schema, when it has one, is dropped afterwards."""
    workspace = _launch_workspace(root, fake_immich_server)
    yield workspace
    close_stores()
    if not workspace.store_url.startswith("sqlite"):
        drop_schema(workspace.store_url, workspace.store_schema)


def _store_location(root: Path) -> tuple[str, str]:
    """The workspace's store: a SQLite file in it, or a schema of its own on PostgreSQL."""
    if url := os.environ.get(E2E_DATABASE_ENV):
        return normalize_url(url), f"e2e_{uuid.uuid4().hex[:12]}"
    return f"sqlite:///{root / 'store.db'}", DEFAULT_SCHEMA


def _launch_workspace(root: Path, fake_immich_server: FakeImmichServer) -> LaunchWorkspace:
    database_path = root / "cache" / "launch.db"
    store_url, store_schema = _store_location(root)
    cache_dir = root / "cache"
    output_dir = root / "output"
    config_path = root / "config.yaml"
    log_path = root / "server.log"
    cache_dir.mkdir()
    output_dir.mkdir()
    config_path.write_text(
        yaml.safe_dump(
            {
                "immich": {
                    "url": fake_immich_server.base_url,
                    "api_key": fake_immich_server.api_key,
                    "api_version": "auto",
                },
                "output": {
                    "directory": str(output_dir),
                    "format": "mp4",
                    "resolution": "720p",
                    "codec": "h264",
                    "hdr_mode": "sdr",
                    "quality": "low",
                },
                "cache": {
                    "directory": str(cache_dir),
                    "database": str(database_path),
                    "video_cache_enabled": True,
                    "video_cache_max_size_gb": 1,
                    "video_cache_max_age_days": 1,
                },
                "database": {"url": store_url, "schema": store_schema},
                "upload": {"enabled": False},
                "photos": {"enabled": True},
                # The fixture home is a public landmark; the week by the lake
                # sits about 590 km from it, so trip detection has a trip to find.
                "trips": {"homebase_latitude": 50.8417, "homebase_longitude": 4.3624},
                "advanced": {
                    "hardware": {
                        "enabled": False,
                        "backend": "none",
                        "gpu_decode": False,
                    },
                    "musicgen": {"enabled": False},
                    "ace_step": {"enabled": False},
                    # The demo-mode test needs the switch; the docs screenshots hide it.
                    "server": {"enable_demo_mode": True},
                },
            },
            sort_keys=False,
        )
    )
    return LaunchWorkspace(
        root=root,
        config_path=config_path,
        database_path=database_path,
        store_url=store_url,
        store_schema=store_schema,
        cache_dir=cache_dir,
        output_dir=output_dir,
        log_path=log_path,
    )


_LAUNCH_BOOTSTRAP = """
import os
import sys
from pathlib import Path

import immich_memories.config_loader as config_loader

config_path = Path(sys.argv[1])
state_dir = Path(sys.argv[2])
config_loader.Config.get_default_path = classmethod(lambda cls: config_path)
config_loader.init_config_dir = lambda: state_dir

from tests.e2e.fake_editorial import install_fake_editorial_route

# WHY 1.5 s per stage: a browser reload takes a second or two, and the reload
# test has to land while the six stages are still running.
install_fake_editorial_route(stage_seconds=1.5, models_fetched=sys.argv[4] == "fetched")
# The cuts the web client starts are CLI children: they read the same host from here.
os.environ["E2E_MODELS"] = sys.argv[4]
os.environ["E2E_STAGE_SECONDS"] = "0.5"

from tests.e2e.fake_automation import install_fake_automation, install_hermetic_web_jobs
install_fake_automation(config_path, state_dir)

import uvicorn

from immich_memories.web.server import create_app

app = create_app()
install_hermetic_web_jobs(app, config_path, state_dir)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[3]), log_config=None)
"""

_PRODUCTION_SHORTCUT_ENV = frozenset(
    {
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
)


def _build_launch_environment(home: Path | None = None) -> dict[str, str]:
    """Return a subprocess environment isolated from every provider override."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("IMMICH_MEMORIES_")
        and key not in _PRODUCTION_SHORTCUT_ENV
        and key != "PYTEST_CURRENT_TEST"
    }
    env.update(
        {
            "IMMICH_MEMORIES_AUTH__ENABLED": "false",
            "IMMICH_MEMORIES_STORAGE_SECRET": "launch-smoke-storage-secret",
            "ENABLE_QUADRANTS_HEADER_PRINT": "0",
            "QD_LOG_LEVEL": "error",
        }
    )
    if home is not None:
        # Not every path resolves through the config directory: the default store
        # (and the people registry in it) sits under `Path.home()`, so a launch that
        # keeps the developer's HOME reads the developer's real family.
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    return env


@pytest.fixture(scope="session")
def launch_app_url(
    launch_workspace: LaunchWorkspace,
    unused_tcp_port_factory,
) -> Generator[str, None, None]:
    """Run the app against only the fake service and disposable local state."""
    yield from _serve_launch(launch_workspace, unused_tcp_port_factory(), models_fetched=True)


@pytest.fixture(scope="session")
def automation_workspace(
    tmp_path_factory: pytest.TempPathFactory,
    fake_immich_server: FakeImmichServer,
) -> LaunchWorkspace:
    """A host where nobody has filmed anything yet, so automation has the fixture month to offer.

    The launch workspace fills up with the session's own June films, and a memory that has a
    film is, rightly, never suggested again.
    """
    return _launch_workspace(tmp_path_factory.mktemp("automation"), fake_immich_server)


@pytest.fixture(scope="session")
def automation_app_url(
    automation_workspace: LaunchWorkspace,
    unused_tcp_port_factory,
) -> Generator[str, None, None]:
    yield from _serve_launch(automation_workspace, unused_tcp_port_factory(), models_fetched=True)


@pytest.fixture(scope="session")
def first_launch_workspace(
    tmp_path_factory: pytest.TempPathFactory,
    fake_immich_server: FakeImmichServer,
) -> Generator[LaunchWorkspace]:
    """Disposable state for a host where nobody has run `immich-memories models fetch`."""
    yield from _owned_workspace(tmp_path_factory.mktemp("first-launch"), fake_immich_server)


@pytest.fixture(scope="session")
def first_launch_app_url(
    first_launch_workspace: LaunchWorkspace,
    unused_tcp_port_factory,
) -> Generator[str, None, None]:
    """The same launch as `launch_app_url`, on that host."""
    yield from _serve_launch(
        first_launch_workspace, unused_tcp_port_factory(), models_fetched=False
    )


def _serve_launch(
    workspace: LaunchWorkspace, port: int, *, models_fetched: bool
) -> Generator[str, None, None]:
    url = f"http://127.0.0.1:{port}"
    env = _build_launch_environment(workspace.root)

    venv_python = _REPO_ROOT / ".venv" / "bin" / "python"
    with workspace.log_path.open("w") as log_file:
        proc = subprocess.Popen(
            [
                str(venv_python),
                "-c",
                _LAUNCH_BOOTSTRAP,
                str(workspace.config_path),
                str(workspace.root / "state"),
                str(port),
                "fetched" if models_fetched else "never-fetched",
            ],
            stdout=log_file,
            stderr=log_file,
            cwd=_REPO_ROOT,
            env=env,
        )
        try:
            _wait_for_server(
                proc,
                base_url=url,
                log_path=workspace.log_path,
            )
            yield url
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def fake_immich_server(tmp_path_factory: pytest.TempPathFactory) -> Generator[FakeImmichServer]:
    """Run the deterministic Immich v3 test service for this test session."""
    server = FakeImmichServer.start(tmp_path_factory.mktemp("fake-immich"))
    try:
        yield server
    finally:
        server.close()


@pytest.fixture(scope="session")
def app_url() -> Generator[str, None, None]:
    """Yield the base URL of a running UI server.

    Reuses an existing server if one is already listening on :8099,
    otherwise starts one under `coverage run` (with auth disabled)
    and tears it down after the session.
    """
    if _server_is_ready():
        yield _BASE_URL
        return

    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["IMMICH_MEMORIES_AUTH__ENABLED"] = "false"
    # Don't enable demo mode via config — we inject the CSS class directly
    # in enable_demo_mode(). The toggle would show in screenshots otherwise.
    env["COVERAGE_FILE"] = str(_SERVER_COVERAGE_FILE)

    venv_bin = _REPO_ROOT / ".venv" / "bin"
    proc = subprocess.Popen(
        [
            str(venv_bin / "coverage"),
            "run",
            "--source=immich_memories",
            "--branch",
            str(venv_bin / "immich-memories"),
            "ui",
            "--port",
            str(_BASE_PORT),
            "--host",
            "localhost",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        _wait_for_server(proc)
        yield _BASE_URL
    finally:
        # WHY: SIGINT (not SIGTERM) — uvicorn handles SIGINT gracefully and
        # runs atexit hooks, which is how coverage writes its data file.
        # SIGTERM skips atexit in uvicorn.
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        _convert_server_coverage()


@pytest.fixture(scope="session")
def browser_context_args() -> dict:
    """Override pytest-playwright default viewport to match screenshot size."""
    return {"viewport": {"width": 1440, "height": 900}}


@pytest.fixture(scope="session")
def demo_raw_dir() -> Path:
    """Directory for raw demo video recordings."""
    out = _REPO_ROOT / "docs-site" / "static" / "demo" / "raw"
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture(scope="session")
def screenshot_dir() -> Path:
    """Path to the docs-site screenshot directory."""
    repo_root = Path(__file__).resolve().parents[2]
    out = repo_root / "docs-site" / "static" / "img" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    return out


def set_theme(page: Page, theme: str) -> None:
    """Switch the web client to the given theme ('light' or 'dark')."""
    if "/app/" in page.url:
        # @immich/ui keeps the choice in localStorage, JSON-encoded.
        page.evaluate(
            "theme => localStorage.setItem('immich-ui-theme', JSON.stringify(theme))", theme
        )
        page.reload(wait_until="networkidle")
        page.mouse.move(640, 450)
        return
    raise ValueError(f"set_theme needs a web client page, not {page.url}")


def enable_demo_mode(page: Page) -> None:
    """Activate demo mode (CSS blur on all media) for privacy."""
    page.evaluate("document.body.classList.add('demo-mode')")


# -- helpers ------------------------------------------------------------------


def _convert_server_coverage() -> None:
    """Convert server .coverage data to XML and merge with pytest's coverage."""
    if not _SERVER_COVERAGE_FILE.exists():
        return
    subprocess.run(
        ["uv", "run", "coverage", "xml", "-o", str(_REPO_ROOT / "tests" / "e2e-coverage.xml")],
        env={**os.environ, "COVERAGE_FILE": str(_SERVER_COVERAGE_FILE)},
        cwd=str(_REPO_ROOT),
        capture_output=True,
    )
    _SERVER_COVERAGE_FILE.unlink(missing_ok=True)


def _server_is_ready(base_url: str = _BASE_URL) -> bool:
    try:
        r = httpx.get(base_url, timeout=2.0, follow_redirects=True)
        return r.status_code < 500
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


def _process_log_tail(proc: subprocess.Popen, log_path: Path | None) -> str:  # type: ignore[type-arg]
    """Return bounded startup diagnostics from a log file or captured pipes."""
    if log_path is not None and log_path.exists():
        return log_path.read_text(errors="replace")[-4000:]
    stdout = (proc.stdout.read() if proc.stdout else b"").decode(errors="replace")
    stderr = (proc.stderr.read() if proc.stderr else b"").decode(errors="replace")
    return f"{stdout}\n{stderr}"[-4000:]


def _wait_for_server(
    proc: subprocess.Popen,  # type: ignore[type-arg]
    *,
    base_url: str = _BASE_URL,
    log_path: Path | None = None,
) -> None:
    """Wait for one E2E app process or fail with its bounded log tail."""
    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(
                f"UI server exited early with code {proc.returncode}:\n"
                f"{_process_log_tail(proc, log_path)}"
            )
        if _server_is_ready(base_url):
            return
        time.sleep(0.5)
    proc.terminate()
    proc.wait(timeout=5)
    pytest.fail(
        f"UI server did not start within {_STARTUP_TIMEOUT}s:\n{_process_log_tail(proc, log_path)}"
    )
