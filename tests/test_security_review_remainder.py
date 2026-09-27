"""The security findings left open from docs/reviews/2026-08-18-security-perf-review.md.

S3 (rate limiter behind a proxy), S5 (stored XSS in the config viewer),
S10 (unbounded music upload), S16 (secrets partly shown).
"""

from __future__ import annotations

from immich_memories.config_models_auth import AuthConfig


class TestS5ConfigViewerEscapesValues:
    """immich.url is editable from the browser and persisted; rendering it into
    ui.html with an f-string made it stored XSS for the next admin visit. The
    settings page now puts every value in an input widget, which renders text."""

    def test_the_settings_page_renders_no_raw_html(self):
        import inspect

        from immich_memories.ui.pages import settings_config

        assert "ui.html" not in inspect.getsource(settings_config)


def _described(config, tmp_path) -> dict:
    from immich_memories.config_sources import describe_settings

    entries = describe_settings(config, path=tmp_path / "absent.yaml", stored_keys=set())
    return {entry.key: entry.value for entry in entries}


class TestS16SecretsAreFullyMasked:
    """abc***yz leaks five characters of every secret, auth.password included."""

    def test_no_characters_of_the_secret_survive(self, tmp_path):
        from immich_memories.config_loader import Config

        values = _described(Config(immich={"api_key": "abcdefghijklmnop"}), tmp_path)

        assert values["immich.api_key"] == "***"

    def test_an_empty_secret_stays_empty(self, tmp_path):
        from immich_memories.config_loader import Config

        assert _described(Config(immich={"api_key": ""}), tmp_path)["immich.api_key"] == ""

    def test_no_configured_secret_reaches_the_settings_page(self, tmp_path):
        """The page describes the whole model, so a new secret field is masked by name."""
        from immich_memories.config_loader import Config

        config = Config(editorial={"preparation": {"caption_api_key": "caption-credential"}})

        assert "caption-credential" not in repr(_described(config, tmp_path))


class TestS3RateLimiterSeesTheRealClient:
    """Behind Traefik/nginx every request carries the proxy's IP, so one bad
    actor locks out everyone. Trust X-Forwarded-For only from a trusted peer."""

    def test_the_forwarded_client_is_used_when_the_peer_is_trusted(self):
        from immich_memories.ui.auth import client_ip_for_rate_limit

        ip = client_ip_for_rate_limit(
            peer_ip="10.0.0.5",
            forwarded_for="203.0.113.9, 10.0.0.5",
            auth_config=AuthConfig(trusted_proxies=["10.0.0.0/8"]),
        )

        assert ip == "203.0.113.9"

    def test_an_untrusted_peer_cannot_spoof_its_bucket(self):
        from immich_memories.ui.auth import client_ip_for_rate_limit

        ip = client_ip_for_rate_limit(
            peer_ip="198.51.100.7",
            forwarded_for="1.2.3.4",
            auth_config=AuthConfig(trusted_proxies=["10.0.0.0/8"]),
        )

        assert ip == "198.51.100.7"

    def test_no_header_means_the_peer(self):
        from immich_memories.ui.auth import client_ip_for_rate_limit

        ip = client_ip_for_rate_limit(
            peer_ip="10.0.0.5",
            forwarded_for=None,
            auth_config=AuthConfig(trusted_proxies=["10.0.0.0/8"]),
        )

        assert ip == "10.0.0.5"


class TestS10MusicUploadIsBounded:
    def test_the_upload_declares_a_size_cap(self):
        import inspect

        from immich_memories.ui.pages import step3_options

        source = inspect.getsource(step3_options)

        assert "max_file_size" in source

    def test_a_non_audio_payload_is_rejected(self):
        from immich_memories.ui.pages.step3_options import is_supported_audio

        assert is_supported_audio("track.mp3", b"ID3\x04\x00\x00\x00")
        assert not is_supported_audio("evil.mp3", b"MZ\x90\x00\x03\x00\x00\x00")
        assert not is_supported_audio("evil.exe", b"ID3\x04\x00\x00\x00")
