"""Reading run history with another installation's config leaves this home untouched."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from immich_memories.cli import main


def _other_installation(tmp_path: Path, *, own_cache: bool = False) -> Path:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    config = elsewhere / "config.yaml"
    text = "immich:\n  url: http://immich.invalid\n  api_key: k\n"
    if own_cache:
        text += f"cache:\n  directory: {elsewhere / 'cache'}\n"
    config.write_text(text)
    return config


@pytest.mark.feature("docs.first-run-wording")
@pytest.mark.parametrize("command", [["runs", "list"], ["runs", "stats"], ["runs", "storage"]])
def test_reading_runs_creates_no_scratch_in_the_home(tmp_path, monkeypatch, command):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    home_scratch = Path.home() / ".immich-memories" / "cache" / "scratch"
    config = _other_installation(tmp_path)

    # The suite pins the cache to a sandbox; a user's own config has no such variable.
    result = CliRunner().invoke(
        main, ["-c", str(config), *command], env={"IMMICH_MEMORIES_CACHE__DIRECTORY": None}
    )

    assert result.exit_code == 0, result.output
    assert not home_scratch.exists()
    assert not (Path.home() / ".immich-memories" / "cache").exists()


def test_runs_that_change_things_still_keep_scratch_on_the_configured_cache(tmp_path):
    config = _other_installation(tmp_path, own_cache=True)

    result = CliRunner().invoke(
        main,
        ["-c", str(config), "runs", "delete", "nope", "--yes"],
        env={"IMMICH_MEMORIES_CACHE__DIRECTORY": None},
    )

    assert result.exit_code != 0 or "not found" in result.output.lower()
    assert (tmp_path / "elsewhere" / "cache" / "scratch").is_dir()
