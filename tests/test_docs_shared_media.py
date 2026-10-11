"""Docs tracks share the stable tree's copy of byte-identical large media."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.docs_shared_media import assemble, select_shared

ROOT = Path(__file__).resolve().parents[1]
MB = 1024 * 1024


def test_identical_large_files_are_shared():
    own = {"demo/a.mp4": "blob1", "demo/b.mp4": "blob2", "img/small.png": "blob3"}
    stable = {"demo/a.mp4": "blob1", "demo/b.mp4": "other", "img/small.png": "blob3"}
    sizes = {"demo/a.mp4": 30 * MB, "demo/b.mp4": 30 * MB, "img/small.png": 10_000}
    # b differs from stable: the track keeps its own copy. small is below the threshold.
    assert select_shared(own, stable, sizes, min_size=256 * 1024) == ["demo/a.mp4"]


def test_a_file_stable_does_not_have_is_kept():
    assert select_shared({"demo/new.mp4": "x"}, {}, {"demo/new.mp4": 30 * MB}, 1) == []


def _tree(root: Path, files: dict[str, bytes], html: str = "") -> Path:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "index.html").write_text(html)
    return root


def _tracks(*names):
    paths = {"stable": "", "next": "next", "dev": "dev"}
    return [{"track": name, "path": paths[name]} for name in names]


def test_assembly_drops_a_shared_copy_and_keeps_everything_else(tmp_path):
    trees = tmp_path / "tracks"
    _tree(trees / "docs-stable", {"demo/a.mp4": b"A" * 100, "demo/b.mp4": b"old"})
    _tree(
        trees / "docs-dev",
        {"demo/a.mp4": b"A" * 100, "demo/b.mp4": b"new", "shared-media.json": b'["demo/a.mp4"]'},
        html='<video src="/immich-memories/demo/a.mp4"></video>'
        '<video src="/immich-memories/dev/demo/b.mp4"></video>',
    )
    site = tmp_path / "site"
    sizes = assemble(_tracks("stable", "dev"), trees, site, max_bytes=10 * MB)
    assert (site / "demo/a.mp4").read_bytes() == b"A" * 100
    assert not (site / "dev/demo/a.mp4").exists()
    # The differing file was never listed: dev keeps its own bytes.
    assert (site / "dev/demo/b.mp4").read_bytes() == b"new"
    assert not (site / "dev/shared-media.json").exists()
    assert set(sizes) == {"stable", "dev"}


def test_a_lone_track_downloaded_without_its_folder_is_assembled(tmp_path):
    # download-artifact extracts a single matching artifact straight into its path.
    trees = _tree(tmp_path / "tracks", {"demo/a.mp4": b"A"}, html="stable")
    site = tmp_path / "site"
    assert set(assemble(_tracks("stable"), trees, site, max_bytes=10 * MB)) == {"stable"}
    assert (site / "index.html").read_text() == "stable"
    assert (site / "demo/a.mp4").read_bytes() == b"A"


def test_a_listed_file_whose_bytes_differ_from_stable_fails_the_deploy(tmp_path):
    trees = tmp_path / "tracks"
    _tree(trees / "docs-stable", {"demo/a.mp4": b"stable"})
    _tree(trees / "docs-dev", {"demo/a.mp4": b"dev", "shared-media.json": b'["demo/a.mp4"]'})
    with pytest.raises(ValueError, match="differs from the stable copy"):
        assemble(_tracks("stable", "dev"), trees, tmp_path / "site", max_bytes=10 * MB)


def test_a_copy_a_page_still_links_is_kept(tmp_path):
    trees = tmp_path / "tracks"
    _tree(trees / "docs-stable", {"demo/a.mp4": b"A", "demo/b.mp4": b"B"})
    _tree(
        trees / "docs-next",
        {
            "demo/a.mp4": b"A",
            "demo/b.mp4": b"B",
            "shared-media.json": b'["demo/a.mp4", "demo/b.mp4"]',
        },
        html='<a href="/immich-memories/next/demo/a.mp4">download</a>',
    )
    assemble(_tracks("stable", "next"), trees, tmp_path / "site", max_bytes=10 * MB)
    assert (tmp_path / "site/next/demo/a.mp4").exists()
    assert not (tmp_path / "site/next/demo/b.mp4").exists()


def test_a_track_built_without_a_list_keeps_all_its_files(tmp_path):
    trees = tmp_path / "tracks"
    _tree(trees / "docs-stable", {"demo/a.mp4": b"A"})
    _tree(trees / "docs-next", {"demo/a.mp4": b"A"})
    assemble(_tracks("stable", "next"), trees, tmp_path / "site", max_bytes=10 * MB)
    assert (tmp_path / "site/next/demo/a.mp4").exists()


def test_an_oversized_site_fails_the_deploy(tmp_path):
    trees = tmp_path / "tracks"
    _tree(trees / "docs-stable", {"demo/a.mp4": b"A" * 2048})
    _tree(trees / "docs-dev", {"demo/a.mp4": b"B" * 2048})
    with pytest.raises(ValueError, match="over the 3 KiB limit"):
        assemble(_tracks("stable", "dev"), trees, tmp_path / "site", max_bytes=3 * 1024)


def test_select_command_reads_the_two_refs(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True, env=env).strip()

    git("init", "-q")
    git("config", "user.name", "Docs test")
    git("config", "user.email", "docs@example.test")
    static = tmp_path / "docs-site/static/demo"
    static.mkdir(parents=True)
    (static / "same.mp4").write_bytes(b"S" * 4096)
    (static / "changed.mp4").write_bytes(b"1" * 4096)
    git("add", ".")
    git("commit", "-qm", "stable")
    git("tag", "v1.0.0")
    (static / "changed.mp4").write_bytes(b"2" * 4096)
    git("commit", "-qam", "main")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/docs_shared_media.py"),
            "select",
            "--stable-ref",
            "v1.0.0",
            "--min-size",
            "1024",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["demo/same.mp4"]


def test_docs_workflow_shares_media_and_checks_the_size():
    workflow = yaml.safe_load((ROOT / ".github/workflows/docs.yml").read_text())
    build_steps = workflow["jobs"]["build"]["steps"]
    select = next(
        step for step in build_steps if step.get("name") == "List media shared with stable"
    )
    assert select["if"] == "matrix.track != 'stable'"
    assert "--stable-ref" in select["run"]
    place = next(
        step
        for step in workflow["jobs"]["assemble"]["steps"]
        if step.get("name") == "Place each track at its path"
    )
    assert "scripts/docs_shared_media.py assemble" in place["run"]
    assert "--max-mb 900" in place["run"]
