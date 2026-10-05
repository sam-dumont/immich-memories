from immich_memories.config_loader import Config, load_config
from immich_memories.preflight import CheckStatus
from immich_memories.preflight_store import check_store_location


def test_an_upgrading_config_users_old_store_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    old_store = tmp_path / "home" / ".immich-memories" / "store.db"
    old_store.parent.mkdir(parents=True)
    old_store.write_text("")
    config = load_config(tmp_path / "other-library" / "config.yaml")

    result = check_store_location(config)

    assert result.status is CheckStatus.WARNING
    assert str(old_store) in result.details


def test_the_default_config_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    result = check_store_location(Config())

    assert result.status is CheckStatus.OK
