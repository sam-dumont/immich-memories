"""What the preflight rows say, for someone who has never seen the app before."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from immich_memories.api.permissions import READ_PERMISSIONS, UPLOAD_PERMISSIONS, ApiKeyCapabilities
from immich_memories.config_loader import Config, _apply_env_overrides
from immich_memories.preflight import CheckStatus, check_llm
from immich_memories.preflight_immich import check_immich


def _immich_row(permissions: set[str]):
    config = Config(immich={"url": "https://immich.example.com", "api_key": "k"})
    # WHY: replace the external Immich server; the permission logic under test is real.
    client = MagicMock()
    client.__enter__.return_value = client
    client.get_key_capabilities.return_value = ApiKeyCapabilities(frozenset(permissions))
    client.get_current_user.return_value.name = "Sam"
    with patch("immich_memories.api.immich.SyncImmichClient", return_value=client):
        return check_immich(config)


def test_missing_read_permissions_are_named_in_the_row() -> None:
    row = _immich_row(set(READ_PERMISSIONS) - {"map.search"})
    assert row.status is CheckStatus.ERROR
    assert row.message == "Required read permissions missing: map.search"


def test_read_only_key_row_says_why_it_warns() -> None:
    row = _immich_row(set(READ_PERMISSIONS) | {"asset.delete"})
    assert row.status is CheckStatus.WARNING
    assert row.message == "Connected as Sam; upload permissions not granted, films stay local"


def test_fully_permitted_key_row_stays_plain() -> None:
    row = _immich_row(set(READ_PERMISSIONS) | set(UPLOAD_PERMISSIONS) | {"asset.delete"})
    assert row.status is CheckStatus.OK
    assert row.message == "Connected as Sam"


def test_a_key_exported_for_other_tools_is_not_a_configured_reader(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-shell")
    config = Config()
    _apply_env_overrides(config)
    row = check_llm(config)
    assert row.status is CheckStatus.SKIPPED
    assert row.message == "LLM disabled"
