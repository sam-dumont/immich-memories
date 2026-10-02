"""Package tracked deployment files with the release's app and inference tags."""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import tarfile
from pathlib import Path

_APP_IMAGE = rb"ghcr\.io/sam-dumont/immich-video-memory-generator(?:/inference)?"
_IMAGE_PIN = re.compile(rb"(- name: " + _APP_IMAGE + rb'\s*\n\s*newTag: )"([^"\n]+)"')


def pin_images(data: bytes, version: str) -> bytes:
    """Pin app/inference images in any wrapper or component, keeping CUDA variants."""

    def stamped(match: re.Match[bytes]) -> bytes:
        suffix = "-cuda" if match[2].endswith(b"-cuda") else ""
        return match[1] + f'"{version}{suffix}"'.encode()

    return _IMAGE_PIN.sub(stamped, data)


def package_bundle(root: Path, version: str, destination: Path) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+(-rc\.\d+)?", version):
        raise ValueError("Expected a release version without the v prefix")
    # Only tracked files: local secrets and terraform state must never enter a release.
    paths = (
        subprocess.check_output(["git", "ls-files", "-z", "--", "deploy"], cwd=root)
        .decode()
        .split("\0")
    )
    with tarfile.open(destination, "w:gz") as archive:
        for name in filter(None, paths):
            path = root / name
            if path.is_symlink():
                raise ValueError(f"Deployment bundle cannot follow symlink: {name}")
            data = path.read_bytes()
            if name.endswith("kustomization.yaml"):
                data = pin_images(data, version)
            if name.endswith("terraform.tfvars.example"):
                data = re.sub(
                    rb'(?m)^image_tag\s*=\s*"[^"]+"',
                    f'image_tag = "{version}"'.encode(),
                    data,
                )
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            archive.addfile(info, io.BytesIO(data))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    package_bundle(Path(__file__).resolve().parents[1], args.version, args.destination)
