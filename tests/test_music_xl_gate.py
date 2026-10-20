"""Generated music only when it comes from XL; otherwise the bundled library, and a film says why."""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.audio.generators import ace_step_music_path
from immich_memories.audio.generators.ace_step_model_choice import HostMemory
from immich_memories.config.loader import Config
from immich_memories.generate_music import resolve_music


def _library(tmp_path: Path) -> Path:
    folder = tmp_path / "library" / "happy"
    folder.mkdir(parents=True)
    (folder / "track.mp3").write_bytes(b"not really an mp3")
    return tmp_path / "library"


def _film_music(config: Config, tmp_path: Path):
    return resolve_music(
        config,
        None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path,
        memory_type=None,
        bundled_library=_library(tmp_path),
        transition_overlap=0.0,
    )


@pytest.fixture
def generated(monkeypatch) -> list[str]:
    calls: list[str] = []

    def fake_generate(*_args, **_kwargs):
        calls.append("generated")
        return None

    # WHY: stands in for the ACE-Step backend; the test asks whether it is called at all.
    monkeypatch.setattr("immich_memories.generate_music.auto_generate_music", fake_generate)
    return calls


def test_a_small_mac_plays_the_bundled_library_and_says_why(tmp_path, monkeypatch, generated):
    # WHY: a Mac with 32 GB, below the XL bar.
    monkeypatch.setattr(ace_step_music_path, "measure_host", lambda: HostMemory(unified_gib=32.0))
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python", lambda: tmp_path
    )
    config = Config(ace_step={"enabled": True, "mode": "lib"})

    selection = _film_music(config, tmp_path)

    assert generated == []
    assert selection.path is not None and selection.path.suffix == ".mp3"
    assert "32 GB" in (selection.warning or "") and "bundled" in (selection.warning or "")


def test_a_server_running_2b_plays_the_bundled_library(tmp_path, monkeypatch, generated):
    # WHY: the ACE-Step server reports a 2B model on /health.
    monkeypatch.setattr(ace_step_music_path, "server_model", lambda _url: "acestep-v15-turbo")
    config = Config(ace_step={"enabled": True, "mode": "api"})

    selection = _film_music(config, tmp_path)

    assert generated == []
    assert selection.path is not None
    assert "acestep-v15-turbo" in (selection.warning or "")


def test_a_server_running_xl_generates(tmp_path, generated):
    config = Config(ace_step={"enabled": True, "mode": "api"})

    selection = _film_music(config, tmp_path)

    assert generated == ["generated"]
    assert "Generated music skipped" not in (selection.warning or "")


def test_a_written_2b_variant_runs_as_written_with_one_warning(tmp_path, monkeypatch, caplog):
    ace_step_music_path._WARNED.clear()
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python", lambda: tmp_path
    )
    settings = Config(ace_step={"enabled": True, "mode": "lib", "model_variant": "turbo"}).ace_step

    with caplog.at_level("WARNING"):
        first = ace_step_music_path.music_path_for(settings)
        second = ace_step_music_path.music_path_for(settings)

    assert first.generate and second.generate
    assert caplog.text.count("loads a 2B model") == 1
