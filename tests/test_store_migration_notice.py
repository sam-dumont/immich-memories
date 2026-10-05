import logging

from immich_memories.config_loader import load_config
from immich_memories.store_migration_notice import log_store_migration_warnings


def test_a_relocated_store_is_logged_once_at_startup(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("IMMICH_MEMORIES_DATABASE_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    old_store = tmp_path / "home" / ".immich-memories" / "store.db"
    old_store.parent.mkdir(parents=True)
    old_store.write_text("")
    config = load_config(tmp_path / "other-library" / "config.yaml")

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log_store_migration_warnings(config)

    assert str(old_store) in caplog.text


def test_nothing_is_logged_for_the_default_config(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("IMMICH_MEMORIES_DATABASE_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = load_config(tmp_path / "home" / ".immich-memories" / "config.yaml")

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        log_store_migration_warnings(config)

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
