"""Files people copy from main name a released image, never `latest`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from scripts.package_compose import package_compose_assets
from scripts.release_pin import PINNED_FILES, newer_release_than_pin, pin_repository

ROOT = Path(__file__).resolve().parents[1]
IMAGE_LINES = (
    "docker-compose.yml",
    "docker-compose.gpu.yml",
    "docker-compose.cuda.yml",
    "docker-compose.gpu-worker.yml",
    "docker-compose.full.yml",
    "docker-compose.postgres.yml",
    "docker-compose.maximalist.yml",
    "docker/hwaccel.inference.yml",
    "example.env",
    "deploy/unraid/immich-memories.xml",
)
VERSION = r"\d+\.\d+\.\d+(?:-rc\.\d+)?"


def _image_lines(name: str) -> list[str]:
    """Lines that name an image or a tag; prose may still say that `latest` exists."""
    keys = ("image", "newTag", "default", "VERSION", "TAG", "Repository", "image_tag", '`"')
    return [
        line
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
        if any(key in line for key in keys) and not line.lstrip().startswith("description")
    ]


@pytest.mark.feature("deploy.pinned-image")
@pytest.mark.parametrize("name", sorted({*IMAGE_LINES, *PINNED_FILES}))
def test_no_shipped_file_says_latest(name):
    offenders = [
        line
        for line in _image_lines(name)
        if re.search(r"(?<![\w.])latest(?:-cuda)?\b", line) and "plus `latest`" not in line
    ]

    assert not offenders, (name, offenders)


def test_every_manifest_and_kustomization_is_listed_for_pinning():
    shipped = {
        str(path.relative_to(ROOT))
        for base in ("deploy/kubernetes", "services/render-worker")
        for path in (ROOT / base).rglob("*.yaml")
        if re.search(r"ghcr\.io/sam-dumont/immich-memories", path.read_text(encoding="utf-8"))
    }

    assert shipped <= set(PINNED_FILES), shipped - set(PINNED_FILES)


@pytest.mark.feature("deploy.pinned-image")
def test_every_pin_names_the_same_release():
    pins = set()
    for name in PINNED_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        pins |= set(re.findall(rf"IMMICH_MEMORIES_VERSION[:=-]+({VERSION})", text))
        pins |= set(re.findall(rf"immich-memories:({VERSION})</Repository>", text))
        pins |= set(re.findall(rf"VERSION=({VERSION})\b", text))
        pins |= set(re.findall(rf"(?:newTag: \"|immich-memories(?:/inference)?:)({VERSION})", text))
        pins |= set(re.findall(rf"default\s*=\s*\"({VERSION})\"", text))

    assert len(pins) == 1, pins


@pytest.mark.feature("deploy.pinned-image")
def test_the_unraid_template_pulls_the_pinned_release():
    text = (ROOT / "deploy/unraid/immich-memories.xml").read_text(encoding="utf-8")

    assert re.search(
        rf"<Repository>ghcr\.io/sam-dumont/immich-memories:{VERSION}</Repository>", text
    )


def test_pinning_a_new_release_moves_every_file_and_the_builder_sources(tmp_path):
    for name in PINNED_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")

    pin_repository(tmp_path, "7.8.9-rc.1")

    for name in PINNED_FILES:
        assert "7.8.9-rc.1" in (tmp_path / name).read_text(encoding="utf-8"), name
    cuda = (tmp_path / "docker-compose.cuda.yml").read_text(encoding="utf-8")
    assert "inference:${IMMICH_MEMORIES_VERSION:-7.8.9-rc.1}-cuda" in cuda


def test_release_assets_stamp_the_release_over_the_pin(tmp_path):
    package_compose_assets(ROOT, "7.8.9", tmp_path)

    assert "IMMICH_MEMORIES_VERSION=7.8.9" in (tmp_path / "example.env").read_text()
    assert (
        "immich-memories:${IMMICH_MEMORIES_VERSION:-7.8.9}"
        in (tmp_path / "docker-compose.yml").read_text()
    )


def test_pinning_moves_the_readme_browser_urls_to_the_shipped_host_port(tmp_path):
    for name in PINNED_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        re.sub(r":\d+:8080\b", ":18081:8080", compose.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    pin_repository(tmp_path, "7.8.9-rc.1")

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "http://localhost:18081" in readme
    assert "http://your-server-address:18081" in readme
    assert not re.search(r"http://(?:localhost|your-server-address):(?!18081)\d+", readme)


TAGS = ["v0.103.0", "v1.0.0-rc.2", "v1.0.0-rc.9", "v1.0.0-rc.10", "nightly", "nightly-20261014"]


@pytest.mark.parametrize(
    ("pinned", "tags", "behind"),
    [
        ("1.0.0-rc.9", TAGS, "1.0.0-rc.10"),
        ("1.0.0-rc.10", TAGS, None),
        ("1.0.0-rc.10", [*TAGS, "v1.0.0"], "1.0.0"),
        ("1.0.0", [*TAGS, "v1.0.0"], None),
    ],
)
def test_a_release_refuses_to_start_while_main_pins_an_older_release(pinned, tags, behind):
    readme = f"   VERSION={pinned}\n"

    assert newer_release_than_pin(readme, tags) == behind
