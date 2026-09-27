"""Secure-by-default binding (#476): auth off means localhost unless the
operator says otherwise — in config or on the command line."""

from __future__ import annotations

from pathlib import Path

from immich_memories.config_loader import Config


def _config(**overrides) -> Config:
    return Config(**overrides)


class TestEffectiveHost:
    def test_auth_off_and_nothing_set_binds_localhost(self):
        config = _config()

        host = config.server.effective_host(auth_enabled=config.auth.enabled)

        assert host == "127.0.0.1"

    def test_auth_on_keeps_the_configured_default(self):
        config = _config()

        # auth validity is AuthConfig's concern; the resolver only needs the flag
        assert config.server.effective_host(auth_enabled=True) == "0.0.0.0"  # noqa: S104 — the assertion IS about the broad bind

    def test_an_explicit_host_is_the_operators_decision(self):
        config = _config(server={"host": "0.0.0.0"})  # noqa: S104 — explicit operator choice under test

        assert config.server.effective_host(auth_enabled=False) == "0.0.0.0"  # noqa: S104 — the assertion IS about the broad bind

    def test_the_named_escape_hatch_works(self):
        config = _config(server={"allow_unauthenticated_lan": True})

        assert config.server.effective_host(auth_enabled=False) == "0.0.0.0"  # noqa: S104 — the assertion IS about the broad bind


class TestConfigsAlreadyCarryingTheWildcard:
    """#507 migration: the wildcard the app used to write is not a decision."""

    def test_a_file_written_by_an_older_version_binds_localhost(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("advanced:\n  server:\n    host: 0.0.0.0\n    port: 9090\n")

        reloaded = Config.from_yaml(config_path)

        assert reloaded.server.port == 9090
        assert reloaded.server.effective_host(auth_enabled=False) == "127.0.0.1"

    def test_the_env_var_is_still_a_decision(self, tmp_path: Path, monkeypatch) -> None:
        """Only the file is ambiguous — nothing ever wrote the env var but a human."""
        monkeypatch.setenv("IMMICH_MEMORIES_SERVER__HOST", "0.0.0.0")  # noqa: S104 — the operator's choice under test
        config_path = tmp_path / "config.yaml"
        config_path.write_text("advanced:\n  server:\n    host: 0.0.0.0\n")

        reloaded = Config.from_yaml(config_path)

        assert reloaded.server.effective_host(auth_enabled=False) == "0.0.0.0"  # noqa: S104 — the assertion IS about the broad bind
