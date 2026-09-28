"""The shipped image, run the way a self-hoster runs it: `docker-compose.yml` and a volume.

`Deployment` drives the repo's own compose file through the docker CLI. The file is used
as it ships; the only changes are the ones a user makes: an image to run, the commented
PostgreSQL example switched on, and the environment in `.env`. A small override file
renames the containers and drops the published port, so a run never collides with a
real install on the same machine.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
APP = "immich-memories"
APP_HOME = "/home/immich/.immich-memories"
# The CronJob's own client (deploy/kubernetes/base/job.yaml), pinned the same way.
CURL_IMAGE = (
    "docker.io/curlimages/curl:8.11.1"
    "@sha256:c1fe1679c34d9784c1b0d1e5f62ac0a79fca01fb6377cdd33e90473c6f9f9a69"
)
TRIGGER_TOKEN = "container-e2e-trigger-token"  # noqa: S105 -- throwaway test deployment
POSTGRES_PASSWORD = "container-e2e-password"  # noqa: S105 -- throwaway test deployment
_COUNT_LINE = re.compile(r"^\s{2}(?P<table>[a-z_]+)\s+(?P<count>\d+)$")


class DeploymentError(AssertionError):
    """A docker command the suite depends on failed."""


def switch_on_postgres(compose: str) -> str:
    """The compose file with its commented PostgreSQL example uncommented, as a user would."""
    lines = compose.splitlines()
    url = [
        i
        for i, line in enumerate(lines)
        if line.lstrip().startswith("# IMMICH_MEMORIES_DATABASE_URL:")
    ]
    service = [i for i, line in enumerate(lines) if line == "  # postgres:"]
    volume = [i for i, line in enumerate(lines) if line == "  # immich-memories-postgres-data:"]
    if len(url) != 1 or len(service) != 1 or len(volume) != 1:
        raise DeploymentError("docker-compose.yml no longer carries the PostgreSQL example")
    lines[url[0]] = lines[url[0]].replace("# ", "", 1)
    index = service[0]
    while index < len(lines) and lines[index].startswith("  #"):
        lines[index] = "  " + lines[index][4:]
        index += 1
    lines[volume[0]] = "  immich-memories-postgres-data:"
    return "\n".join(lines) + "\n"


def parse_counts(status: str) -> dict[str, int]:
    """Per-table row counts from `store status`."""
    return {
        match["table"]: int(match["count"])
        for line in status.splitlines()
        if (match := _COUNT_LINE.match(line))
    }


@dataclass
class Deployment:
    """One compose project: the app on its volume, and PostgreSQL when the backend asks."""

    image: str
    backend: str
    root: Path
    project: str = field(default_factory=lambda: f"imc-{uuid.uuid4().hex[:8]}")

    @property
    def postgres(self) -> bool:
        return self.backend == "postgresql"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    def write(self) -> None:
        """Lay out the compose project a user would have: the file, `.env`, `./output`."""
        self.root.mkdir(parents=True, exist_ok=True)
        compose = COMPOSE_FILE.read_text()
        (self.root / "docker-compose.yml").write_text(
            switch_on_postgres(compose) if self.postgres else compose
        )
        (self.root / ".env").write_text(
            # Refused at once: the trigger's run records a failed attempt, not a hang.
            "IMMICH_URL=http://127.0.0.1:9\n"
            "IMMICH_API_KEY=container-e2e-not-a-key\n"
            f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}\n"
        )
        self.output_dir.mkdir(exist_ok=True)
        # The container runs as uid 1000; a runner's checkout belongs to someone else.
        self.output_dir.chmod(0o777)
        (self.root / "override.yml").write_text(self._override())

    def _override(self) -> str:
        # `!reset` drops the published port rather than adding to it: a run must not
        # take the port a real install on this machine may already hold.
        override = f"""services:
  {APP}:
    image: {self.image}
    container_name: {self.project}-app
    ports: !reset []
    environment:
      IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN: {TRIGGER_TOKEN}
      IMMICH_MEMORIES_AUTOMATION__UPLOAD_TO_IMMICH: "false"
"""
        if self.postgres:
            override += f"""  postgres:
    container_name: {self.project}-postgres
"""
        return override

    def compose(self, *args: str, timeout: int = 600, check: bool = True) -> str:
        command = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(self.root),
            "-f",
            str(self.root / "docker-compose.yml"),
            "-f",
            str(self.root / "override.yml"),
        ]
        if self.postgres:
            command += ["--profile", "postgres"]
        return _run([*command, *args], timeout=timeout, check=check)

    def seed_volume(self, legacy_home: Path) -> None:
        """Put a pre-store `~/.immich-memories` on the config volume, owned by the app user."""
        self.compose(
            "run",
            "--rm",
            "--no-deps",
            "--user",
            "0",
            "--entrypoint",
            "sh",
            "-v",
            f"{legacy_home}:/legacy:ro",
            APP,
            "-c",
            f"cp -a /legacy/. {APP_HOME}/ && chown -R 1000:1000 {APP_HOME}",
        )

    def up(self) -> None:
        self.compose("up", "-d", "--wait", "--wait-timeout", "300", timeout=420)

    def down(self) -> None:
        self.compose("down", "--volumes", "--remove-orphans", "--timeout", "10", check=False)

    def cli(self, *args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
        """`immich-memories <args>` inside the running app container."""
        flags = [item for key, value in (env or {}).items() for item in ("-e", f"{key}={value}")]
        return self.compose("exec", "-T", *flags, APP, "immich-memories", *args, check=check)

    def scratch_store(self) -> dict[str, str]:
        """The environment that points the app's CLI at an empty store beside the real one.

        On PostgreSQL that is a database of its own on the same server: a restore renames
        the backup's schema, so it cannot land in the database whose schema it came from.
        """
        if not self.postgres:
            return {"IMMICH_MEMORIES_DATABASE_URL": "sqlite:////tmp/restore-scratch.db"}
        self.compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "immich_memories",
            "-d",
            "immich_memories",
            "-c",
            "CREATE DATABASE restore_scratch",
        )
        return {
            "IMMICH_MEMORIES_DATABASE_URL": (
                f"postgresql+psycopg://immich_memories:{POSTGRES_PASSWORD}@postgres:5432/"
                "restore_scratch"
            )
        }

    def shell(self, script: str) -> str:
        return self.compose("exec", "-T", APP, "sh", "-c", script)

    def curl(self, *args: str) -> str:
        """Run the CronJob's curl image on the project's network; its stdout only.

        Docker reports a first pull of the image on stderr, and the answer must parse.
        """
        return _run(
            ["docker", "run", "--rm", "--network", f"{self.project}_default", CURL_IMAGE, *args],
            timeout=120,
            check=True,
            stdout_only=True,
        )

    def trigger_url(self, suffix: str = "") -> str:
        return f"http://{APP}:8080/api/trigger{suffix}"

    def wait_for(self, predicate, what: str, timeout: float = 180.0):
        """Poll `predicate()` until it returns something truthy, or fail naming `what`."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if found := predicate():
                return found
            time.sleep(2)
        raise DeploymentError(f"timed out waiting for {what}\n{self.logs()[-4000:]}")

    def logs(self) -> str:
        return self.compose("logs", "--no-color", APP, check=False)


def copy_tree(source: Path, target: Path) -> None:
    for path in source.iterdir():
        destination = target / path.name
        if path.is_dir():
            shutil.copytree(path, destination)
        else:
            shutil.copy2(path, destination)


def _run(command: list[str], *, timeout: int, check: bool, stdout_only: bool = False) -> str:
    result = subprocess.run(  # noqa: S603 -- the docker CLI, fixed argv
        command, capture_output=True, text=True, timeout=timeout, check=False
    )
    output = result.stdout + result.stderr
    if check and result.returncode != 0:
        raise DeploymentError(
            f"{' '.join(command[:8])} ... exited {result.returncode}:\n{output[-4000:]}"
        )
    return result.stdout if stdout_only else output
