"""Help text and doc redirects that first-run readers meet."""

from __future__ import annotations

import re
from pathlib import Path

from click.testing import CliRunner

from immich_memories.cli import main

ROOT = Path(__file__).resolve().parents[1]


def _help(*args: str) -> str:
    return CliRunner().invoke(main, [*args, "--help"], env={"COLUMNS": "100"}).output


def test_models_fetch_names_the_basic_tier_not_nas():
    text = _help("models", "fetch")

    assert "basic" in text
    assert not re.search(r"\bnas\b", text)


def test_preflight_help_lists_each_check_on_its_own_line():
    lines = _help("preflight").splitlines()

    checks = [line for line in lines if line.startswith("  - ")]
    assert len(checks) == 8


def test_ui_help_says_dash_h_is_host():
    text = " ".join(_help("ui").split())

    assert "-h, --host" in text
    assert "use --help for help" in text


def test_old_doc_urls_redirect_to_pages_that_exist():
    redirects = (ROOT / "docs-site/redirects.ts").read_text(encoding="utf-8")
    pairs = dict(re.findall(r"from: '([^']+)', to: '([^']+)'", redirects))
    docs = ROOT / "docs-site/docs"

    for old in (
        "/docs/configuration/config-file",
        "/docs/installation/uv",
        "/docs/music/overview",
        "/docs/create/pipeline/audio-and-music",
    ):
        target = pairs[old].removeprefix("/docs/")
        assert any((docs / f"{target}{ext}").exists() for ext in (".md", ".mdx", "/index.md")), (
            f"{old} -> {pairs[old]}"
        )
