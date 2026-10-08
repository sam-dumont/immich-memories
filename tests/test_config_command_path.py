"""`--config PATH` is the file `config` reads its overrides from, and no file is ever written.

The command used to save to `Config.get_default_path()` regardless, so
`immich-memories --config ./test.yaml config` wrote the test file's values over
`~/.immich-memories/config.yaml`. Since #871 it saves to the database and
config.yaml is the operator's: a key the named file sets is refused and named,
and neither file changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config_loader import set_config
from immich_memories.db import close_stores


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Iterator[Path]:
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")
    default = tmp_path / "home" / ".immich-memories" / "config.yaml"
    default.parent.mkdir(parents=True)
    default.write_text("immich:\n  url: http://default.invalid:2283\n  api_key: default-key\n")
    yield tmp_path
    set_config(None)
    close_stores()


def _invoke(home: Path, target: Path, *args: str):
    # WHY: the default location must be observable without touching a real home.
    with patch.object(Path, "home", classmethod(lambda _cls: home / "home")):
        return CliRunner().invoke(main, ["--config", str(target), "config", *args], input="n\n")


def test_a_key_the_named_file_sets_is_refused_and_named(home: Path):
    target = home / "alternate.yaml"
    target.write_text("immich:\n  url: http://named.invalid:2283\n")
    before = target.read_text()

    result = _invoke(home, target, "--url", "http://edited.invalid:2283")

    assert result.exit_code == 1
    assert "immich.url" in result.output
    assert target.read_text() == before
    assert "edited.invalid" not in (home / "home/.immich-memories/config.yaml").read_text()


def test_a_key_the_named_file_leaves_open_is_saved_without_writing_either_file(home: Path):
    target = home / "alternate.yaml"
    target.write_text("output:\n  resolution: 720p\n")

    result = _invoke(home, target, "--url", "http://edited.invalid:2283")

    assert result.exit_code == 0, result.output
    assert "edited.invalid" not in target.read_text()
    assert "edited.invalid" not in (home / "home/.immich-memories/config.yaml").read_text()
    shown = _invoke(home, target, "show", "immich.url")
    assert "edited.invalid" in shown.output
    assert "database" in shown.output


@pytest.mark.parametrize("existing", [False, True])
def test_an_explicit_config_does_not_create_or_chmod_the_default_home(
    tmp_path, monkeypatch, existing
):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert Path.home() == home
    owner_state = home / ".immich-memories"
    if existing:
        owner_state.mkdir(mode=0o755)
    config_dir = tmp_path / "other-install"
    config_dir.mkdir()
    config_path = config_dir / "config.yaml"
    config_path.write_text("immich:\n  api_version: auto\n")

    result = CliRunner().invoke(
        main, ["--config", str(config_path), "config", "show", "immich.api_version"]
    )

    assert result.exit_code == 0, result.output
    if existing:
        assert owner_state.stat().st_mode & 0o777 == 0o755
        assert not list(owner_state.iterdir())
    else:
        assert not owner_state.exists()
