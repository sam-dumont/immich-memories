"""Explicit configs keep newly created library caches private without changing other homes."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config_loader import get_config, set_config


@pytest.mark.parametrize("kind", ["thumbnail", "video"])
def test_explicit_config_default_cache_is_created_private(tmp_path, monkeypatch, kind):
    home = tmp_path / "home"
    home.mkdir(mode=0o755)
    monkeypatch.setenv("HOME", str(home))
    assert Path.home() == home
    monkeypatch.delenv("IMMICH_MEMORIES_CACHE__DIRECTORY", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n")
    try:
        result = CliRunner().invoke(
            main, ["--config", str(config_path), "config", "show", "cache.directory"]
        )
        assert result.exit_code == 0, result.output
        config = get_config()
        if kind == "thumbnail":
            from immich_memories.cache.thumbnail_cache import ThumbnailCache

            directory = config.cache.cache_path / "thumbnails"
            cache = ThumbnailCache(directory)
            cached = cache.put("synthetic-id", "preview", b"private picture")
            assert cached.read_bytes() == b"private picture"
        else:
            from immich_memories.cache.video_cache import VideoDownloadCache

            directory = config.cache.video_cache_path
            VideoDownloadCache(directory)
        assert directory.is_relative_to(home)
        assert directory.stat().st_mode & 0o777 == 0o700
        assert home.stat().st_mode & 0o777 == 0o755
    finally:
        set_config(None)


@pytest.mark.parametrize("existing", [False, True])
def test_explicit_config_web_startup_leaves_unused_default_home_alone(
    tmp_path, monkeypatch, existing
):
    from fastapi.testclient import TestClient

    from immich_memories.config_loader import load_config
    from immich_memories.web.server import create_app

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert Path.home() == home
    # A separate web install supplies its own signing key; the default file stays in HOME.
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", "synthetic-session-key-" * 3)
    owner_state = home / ".immich-memories"
    if existing:
        owner_state.mkdir(mode=0o755)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n")
    try:
        load_config(config_path)
        with TestClient(create_app()) as client:
            assert client.get("/health/live").status_code == 200
        if existing:
            assert owner_state.stat().st_mode & 0o777 == 0o755
            assert not list(owner_state.iterdir())
        else:
            assert not owner_state.exists()
    finally:
        set_config(None)


def test_scheduler_launcher_creates_private_directories_in_a_fresh_home(tmp_path, monkeypatch):
    from immich_memories.automation import system_scheduler

    home = tmp_path / "home"
    home.mkdir(mode=0o755)
    monkeypatch.setenv("HOME", str(home))
    assert Path.home() == home
    # WHY: choose the crontab text generator; it returns instructions without executing them.
    monkeypatch.setattr(system_scheduler, "detect_platform", lambda: "crontab")
    # WHY: installation resolves the executable from the host PATH.
    monkeypatch.setattr(
        system_scheduler.shutil, "which", lambda _name: "/opt/app/bin/immich-memories"
    )
    # WHY: refuse every subprocess so this test cannot touch a real OS scheduler.
    monkeypatch.setattr(
        system_scheduler.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("The launcher permission test must not run a subprocess"),
    )

    result = system_scheduler.install_scheduler(config_path=tmp_path / "config.yaml", force=True)

    launcher = home / ".immich-memories" / "bin" / "immich-memories-auto"
    assert launcher in result.files_written
    assert launcher.stat().st_mode & 0o111
    assert launcher.parent.stat().st_mode & 0o777 == 0o700
    assert launcher.parent.parent.stat().st_mode & 0o777 == 0o700
    assert home.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("kind", ["thumbnail", "video"])
def test_existing_media_cache_becomes_private_without_changing_its_parent(tmp_path, kind):
    parent = tmp_path / "shared"
    directory = parent / kind
    directory.mkdir(parents=True)
    parent.chmod(0o755)
    directory.chmod(0o755)
    existing = directory / "old-media.bin"
    existing.write_bytes(b"private library media")
    existing.chmod(0o644)

    if kind == "thumbnail":
        from immich_memories.cache.thumbnail_cache import ThumbnailCache

        ThumbnailCache(directory)
    else:
        from immich_memories.cache.video_cache import VideoDownloadCache

        VideoDownloadCache(directory)

    assert directory.stat().st_mode & 0o777 == 0o700
    assert parent.stat().st_mode & 0o777 == 0o755
    assert existing.read_bytes() == b"private library media"
