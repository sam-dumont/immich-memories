"""Run the real CLI the way a user does, in a sealed home, and read what it leaves behind.

Feature tests drive `immich-memories` as a child process: its own HOME (so the config
sits at the default path and the store and logs land beside it), no provider overrides
from the developer's shell, and wide terminal columns so tables print whole ids. What
they assert on is what a user gets: the exit code, the printed text, the files on disk
and the film itself (`film_facts`, `band_luma`).
"""

from __future__ import annotations

import json
import os
import re
import socket
import statistics
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]

# The child installs the scripted editorial route from the hermetic launch check, then runs
# the real CLI. Only selection is scripted: discovery, the cut record, rendering, the run
# history and every command after it are production code.
_SCRIPTED_SELECTION = """
import sys
from tests.e2e.fake_editorial import install_fake_editorial_route

install_fake_editorial_route(stage_seconds=0.0)

from immich_memories.cli import main

sys.argv = ["immich-memories", *sys.argv[1:]]
main()
"""

_PROVIDER_SHORTCUTS = frozenset(
    {"IMMICH_URL", "IMMICH_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"}
)

RUN_ID = re.compile(r"\d{8}_\d{6}_[0-9a-f]{4}")


@dataclass(frozen=True, slots=True)
class CliResult:
    """One finished CLI run."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr

    def explain(self) -> str:
        """The tail of the output, for an assertion message."""
        return f"immich-memories {' '.join(self.args)} -> {self.returncode}\n{self.output[-4000:]}"


@dataclass(frozen=True, slots=True)
class UserHome:
    """A disposable home directory with an Immich Memories config at the default path."""

    root: Path
    # Added to every child run's environment, e.g. an OutboundTrap's proxy variables.
    extra_env: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def config_path(self) -> Path:
        return self.root / ".immich-memories" / "config.yaml"

    @property
    def videos(self) -> Path:
        return self.root / "Videos"

    def write_config(self, config: dict[str, Any]) -> Path:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        self.config_path.chmod(0o600)
        return self.config_path

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """The developer's environment minus anything that would reach past this home."""
        # WHY: provider variables and IMMICH_MEMORIES_* overrides would point the run at
        # the developer's own library, store or model instead of this home's config.
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("IMMICH_MEMORIES_", "ZAI_", "XDG_"))
            and key not in _PROVIDER_SHORTCUTS
        }
        env.update(
            HOME=str(self.root),
            USERPROFILE=str(self.root),
            # WHY: a table wraps a cell wider than the terminal, splitting a phrase over
            # two lines. A film's path is a temp path, as long as the machine makes it (an
            # xdist worker adds a folder), so no row may depend on fitting 250 columns.
            COLUMNS="1000",
            NO_COLOR="1",
            PYTHONPATH=os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH")])),
        )
        env.update(self.extra_env)
        env.update(extra or {})
        return env

    def run(
        self,
        *args: str,
        scripted_selection: bool = False,
        env: dict[str, str] | None = None,
        timeout: float = 600,
    ) -> CliResult:
        """`immich-memories <args>` as a child process; never raises on a non-zero exit."""
        if scripted_selection:
            command = [sys.executable, "-c", _SCRIPTED_SELECTION, *args]
        else:
            command = [sys.executable, "-m", "immich_memories.cli", *args]
        completed = subprocess.run(  # noqa: S603 -- our own CLI, fixed argv
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self.env(env),
            cwd=self.root,
            check=False,
        )
        return CliResult(tuple(args), completed.returncode, completed.stdout, completed.stderr)


def basic_config(immich_url: str, api_key: str, home: UserHome) -> dict[str, Any]:
    """The smallest Basic install: one Immich, films under ~/Videos, nothing else switched on."""
    return {
        "tier": "basic",
        "immich": {"url": immich_url, "api_key": api_key, "api_version": "auto"},
        "output": {
            "directory": str(home.videos),
            "format": "mp4",
            "resolution": "720p",
            "codec": "h264",
            "hdr_mode": "sdr",
            "quality": "low",
        },
        "upload": {"enabled": False},
        "photos": {"enabled": True},
        # A public landmark, as in the fixture library's own seed.
        "trips": {"homebase_latitude": 50.8417, "homebase_longitude": 4.3624},
        "advanced": {
            "hardware": {"enabled": False, "backend": "none", "gpu_decode": False},
            "musicgen": {"enabled": False},
            "ace_step": {"enabled": False},
        },
    }


# ── what the film is ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FilmFacts:
    """What ffprobe reads from a finished film."""

    duration: float
    width: int
    height: int
    frames: int
    fps: float
    has_audio: bool
    codec: str


def _rate(value: str) -> float:
    numerator, _, denominator = value.partition("/")
    return float(numerator) / float(denominator or 1) if float(denominator or 1) else 0.0


def film_facts(path: Path) -> FilmFacts:
    """Probe a film's container duration, picture size, frame count and streams."""
    probe = subprocess.run(  # noqa: S603 -- fixed ffprobe argv
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,nb_frames,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(probe.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return FilmFacts(
        duration=float(data["format"]["duration"]),
        width=int(video["width"]),
        height=int(video["height"]),
        frames=int(video.get("nb_frames") or 0),
        fps=_rate(video.get("avg_frame_rate", "0/1")),
        has_audio=any(s["codec_type"] == "audio" for s in data["streams"]),
        codec=str(video["codec_name"]),
    )


def band_luma(path: Path, at_seconds: float, *, top_fraction: float = 0.12) -> float:
    """Median luma (0-255, full range) of the top band of the frame shown at `at_seconds`.

    The median, not the mean: a film away from home captions its place in that band,
    and a line of text must not read as picture where the band is a black bar.
    """
    frame = subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"crop=iw:ih*{top_fraction}:0:0,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    if not frame:
        raise AssertionError(f"no frame at {at_seconds}s in {path.name}")
    return float(statistics.median(frame))


def films_under(directory: Path) -> list[Path]:
    """Every finished film under a directory (not the run's working files), oldest first."""
    films = [p for p in directory.rglob("*.mp4") if ".assembling" not in p.name]
    return sorted(films, key=lambda p: p.stat().st_mtime)


# ── what leaves the machine ──────────────────────────────────────────────────


class OutboundTrap:
    """A proxy that refuses everything and remembers what it was asked for.

    A child run pointed at it through HTTP_PROXY/HTTPS_PROXY (with the loopback exempt, so
    the local fake Immich still answers) sends every other HTTP call here first: the
    request line, or the CONNECT target of an HTTPS call, is recorded and refused.
    """

    def __init__(self) -> None:
        self.requests: list[str] = []
        self._server = socket.create_server(("127.0.0.1", 0))
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.getsockname()[1]}"

    def env(self) -> dict[str, str]:
        """Proxy variables for a child run; the loopback stays direct."""
        url = self.url
        return {
            "HTTP_PROXY": url,
            "HTTPS_PROXY": url,
            "ALL_PROXY": url,
            "http_proxy": url,
            "https_proxy": url,
            "all_proxy": url,
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            with connection:
                connection.settimeout(2)
                try:
                    line = connection.recv(4096).split(b"\r\n", 1)[0]
                    self.requests.append(line.decode("latin-1"))
                    connection.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                except OSError:
                    continue

    def close(self) -> None:
        self._server.close()
