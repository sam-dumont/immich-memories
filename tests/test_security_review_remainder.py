"""The security findings left open from docs/reviews/2026-08-18-security-perf-review.md.

S3 (rate limiter behind a proxy), S10 (music upload), S16 (secrets partly shown).
S5 (stored XSS in the config viewer) went with the NiceGUI viewer: the Svelte client
escapes every value it renders.
"""

from __future__ import annotations

from immich_memories.config_models_auth import AuthConfig


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
        from immich_memories.web.auth import client_ip_for_rate_limit

        ip = client_ip_for_rate_limit(
            peer_ip="10.0.0.5",
            forwarded_for="203.0.113.9, 10.0.0.5",
            auth_config=AuthConfig(trusted_proxies=["10.0.0.0/8"]),
        )

        assert ip == "203.0.113.9"

    def test_an_untrusted_peer_cannot_spoof_its_bucket(self):
        from immich_memories.web.auth import client_ip_for_rate_limit

        ip = client_ip_for_rate_limit(
            peer_ip="198.51.100.7",
            forwarded_for="1.2.3.4",
            auth_config=AuthConfig(trusted_proxies=["10.0.0.0/8"]),
        )

        assert ip == "198.51.100.7"

    def test_no_header_means_the_peer(self):
        from immich_memories.web.auth import client_ip_for_rate_limit

        ip = client_ip_for_rate_limit(
            peer_ip="10.0.0.5",
            forwarded_for=None,
            auth_config=AuthConfig(trusted_proxies=["10.0.0.0/8"]),
        )

        assert ip == "10.0.0.5"


class TestS10MusicUploadIsChecked:
    """An upload is kept on disk and later handed to FFmpeg: it has to be audio."""

    def _upload(self, tmp_path, name: str, payload: bytes) -> int:
        from tests.web_api_fixtures import api_client, config_in

        client = api_client(config_in(tmp_path))
        return client.post("/api/v1/music", files={"file": (name, payload)}).status_code

    def test_an_audio_file_is_kept(self, tmp_path):
        assert self._upload(tmp_path, "track.mp3", b"ID3\x04\x00\x00\x00") == 201

    def test_a_non_audio_name_is_rejected(self, tmp_path):
        assert self._upload(tmp_path, "evil.exe", b"ID3\x04\x00\x00\x00") == 422

    def test_a_non_audio_payload_is_rejected(self, tmp_path):
        assert self._upload(tmp_path, "evil.mp3", b"MZ\x90\x00\x03\x00\x00\x00") == 422

    def test_an_upload_past_the_cap_is_refused(self, tmp_path, monkeypatch):
        from immich_memories.web import job_routes

        monkeypatch.setattr(job_routes, "MAX_MUSIC_UPLOAD_BYTES", 16)
        assert self._upload(tmp_path, "long.mp3", b"ID3" + b"\x00" * 64) == 413
