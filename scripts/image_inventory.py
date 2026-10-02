"""Inventory the installed image, then audit its exact third-party Python versions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

LOCAL = {"immich-memories", "immich-memories-music", "immich-memories-render-worker"}
PROBE = (
    "import importlib.metadata as m,json; "
    "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}))"
)


def requirements(installed: dict[str, str], *, advisory: bool = False) -> str:
    """Record exact pins; optionally map official Torch variants to upstream advisories."""
    pins = []
    for name, version in sorted(installed.items()):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version
        ):
            raise ValueError("invalid distribution metadata")
        canonical = re.sub(r"[-_.]+", "-", name).lower()
        if advisory and canonical in {"torch", "torchaudio", "torchvision"}:
            # PyPI cannot index local versions. These official build variants share the
            # public release's advisories; retain their exact identity in requirements.txt.
            version = re.sub(r"\+(?:cpu|cu[0-9]+)$", "", version)
        if canonical not in LOCAL:
            pins.append(f"{name}=={version}\n")
    if not pins:
        raise ValueError("empty third-party dependency inventory")
    return "".join(pins)


def inspect(image: str, entrypoint: str, *args: str) -> str:
    """Read metadata without network, writable root, capabilities or mounted host files."""
    return subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--entrypoint",
            entrypoint,
            image,
            *args,
        ],
        text=True,
        timeout=120,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    installed = json.loads(inspect(args.image, "python", "-c", PROBE))
    (args.output / "python.json").write_text(json.dumps(installed, indent=2) + "\n")
    (args.output / "requirements.txt").write_text(requirements(installed))
    pins = args.output / "advisory-requirements.txt"
    pins.write_text(requirements(installed, advisory=True))
    os_packages = inspect(args.image, "dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n")
    if not os_packages.strip():
        raise ValueError("empty OS package inventory")
    (args.output / "os-packages.tsv").write_text(os_packages)
    identity = subprocess.check_output(["docker", "image", "inspect", args.image], text=True)
    (args.output / "image.json").write_text(identity)
    audit = subprocess.run(
        ["uvx", "pip-audit", "-r", str(pins), "--no-deps", "--disable-pip", "--strict"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=900,
    )
    (args.output / "pip-audit.txt").write_text(audit.stdout)
    return subprocess.run(
        ["python3", "scripts/pip_audit_smart.py", "--audit-exit", str(audit.returncode)],
        input=audit.stdout,
        text=True,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
