"""Where the output directory came from, and whether a container would lose the films."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from immich_memories.preflight import CheckResult, CheckStatus

if TYPE_CHECKING:
    from immich_memories.config import Config

ENV_VARIABLE = "IMMICH_MEMORIES_OUTPUT__DIRECTORY"


@dataclass(frozen=True)
class OutputOrigin:
    """Which source set `output.directory`, and the config.yaml value it displaced, if any."""

    source: str
    value: str | None
    shadowed: str | None

    def describe(self) -> str:
        if self.source == "env":
            return f"from {ENV_VARIABLE}"
        if self.source == "file":
            return "from config.yaml"
        return "from the built-in default"


def output_origin(*, env: Mapping[str, str], config_file_value: str | None) -> OutputOrigin:
    """Env vars win over config.yaml, which wins over the default."""
    wanted = ENV_VARIABLE.upper()
    from_env = next((v for k, v in env.items() if k.upper() == wanted and v), None)
    if from_env:
        shadowed = (
            config_file_value if config_file_value and config_file_value != from_env else None
        )
        return OutputOrigin("env", from_env, shadowed)
    if config_file_value:
        return OutputOrigin("file", config_file_value, None)
    return OutputOrigin("default", None, None)


def config_file_output_directory(config_path: Path) -> str | None:
    """The `output.directory` the config file sets, or None when it sets none or cannot be read."""
    import yaml

    try:
        data: Any = yaml.safe_load(config_path.read_text())
    except (OSError, yaml.YAMLError):
        return None
    output = data.get("output") if isinstance(data, dict) else None
    value = output.get("directory") if isinstance(output, dict) else None
    return str(value) if value else None


def running_in_container(
    exists: Callable[[str], bool] = os.path.exists, env: Mapping[str, str] = os.environ
) -> bool:
    return (
        exists("/.dockerenv")
        or exists("/run/.containerenv")
        or bool(env.get("KUBERNETES_SERVICE_HOST"))
    )


def _device(path: Path) -> int:
    return path.stat().st_dev


def _nearest_existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def output_directory_warnings(
    directory: Path,
    origin: OutputOrigin,
    *,
    in_container: bool,
    device_of: Callable[[Path], int] = _device,
) -> list[CheckResult]:
    """Warnings for an env var shadowing config.yaml, and for films that would not survive."""
    rows: list[CheckResult] = []
    if origin.shadowed is not None:
        rows.append(
            CheckResult(
                name="Output directory",
                status=CheckStatus.WARNING,
                message=(
                    f"{ENV_VARIABLE}={origin.value} overrides config.yaml's "
                    f"output.directory: {origin.shadowed}"
                ),
                details=(
                    "Environment variables win over config.yaml, and the container image sets "
                    f"this one. Films go to {origin.value}. Unset the variable, or set it to "
                    "the directory you mounted"
                ),
            )
        )
    if in_container:
        try:
            on_root_layer = device_of(_nearest_existing(directory)) == device_of(Path("/"))
        except OSError:
            on_root_layer = False
        if on_root_layer:
            rows.append(
                CheckResult(
                    name="Output directory",
                    status=CheckStatus.WARNING,
                    message=(
                        f"{directory} is not a mounted volume: the films are lost when the "
                        "container restarts"
                    ),
                    details=(
                        "Mount a volume or a persistent claim at the output directory "
                        f"(the directory is set {origin.describe()})"
                    ),
                )
            )
    return rows


def output_directory_rows(config: Config) -> list[CheckResult]:
    """The output directory's writability row, naming its source, then any warnings."""
    from immich_memories.config_loader import get_config_path
    from immich_memories.preflight_run import check_output_directory

    directory = config.output.output_path
    origin = output_origin(
        env=os.environ, config_file_value=config_file_output_directory(get_config_path())
    )
    return [
        check_output_directory(directory, origin=origin),
        *output_directory_warnings(directory, origin, in_container=running_in_container()),
    ]
