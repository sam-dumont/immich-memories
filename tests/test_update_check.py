"""The update check: which release is offered, how to install it, and what leaves the machine."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from click.testing import CliRunner

from immich_memories import update_check
from immich_memories.update_check import (
    UpdateCheckFailed,
    check_for_update,
    daily_update_status,
    detect_install_method,
    update_command,
)
from tests.web_api_fixtures import api_client, config_in

# The real builder, kept before a test swaps the module's own for a fake.
_REAL_CLIENT = update_check.release_client


def _release(tag: str, *, draft: bool = False, prerelease: bool = False) -> dict:
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease}


RELEASES = [
    _release("music-v3"),
    _release("nightly", prerelease=True),
    _release("v1.0.1-rc.2", prerelease=True),
    _release("v1.0.1-rc.1", prerelease=True),
    _release("v1.0.1", draft=True),
    _release("v1.0.0"),
    _release("v1.0.0-rc.10", prerelease=True),
    _release("models-v2"),
]


def _config(tmp_path, *, on: bool = False):
    config = config_in(tmp_path)
    config.database.url = f"sqlite:///{tmp_path / 'store.db'}"
    config.updates.check_daily = on
    return config


def _client(releases=RELEASES, seen: list | None = None, status: int = 200) -> httpx.Client:
    def answer(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=releases)

    return _REAL_CLIENT(httpx.MockTransport(answer))


def _check(running: str, *, releases=RELEASES, method: str = "pip"):
    return check_for_update(running, method, _client(releases))


class TestChannels:
    def test_a_stable_install_is_offered_stable_releases_only(self):
        offered = _check("1.0.0")
        assert offered.status == "current"
        offered = _check("0.9.0")
        assert (offered.status, offered.latest) == ("available", "1.0.0")

    def test_a_stable_install_ignores_a_draft_and_candidates(self):
        offered = _check("1.0.0", releases=[_release("v1.0.1", draft=True), *RELEASES])
        assert offered.status == "current"

    def test_a_release_candidate_is_offered_newer_candidates_and_stable_releases(self):
        assert _check("1.0.0rc10").latest == "1.0.1-rc.2"
        assert _check("1.0.1rc2").status == "current"
        only_stable = [_release("v1.0.0"), _release("v1.0.0-rc.3", prerelease=True)]
        assert _check("1.0.0rc3", releases=only_stable).latest == "1.0.0"

    def test_a_nightly_is_offered_the_next_stable_release_not_a_candidate(self):
        releases = [_release("v1.0.0-rc.11", prerelease=True), _release("v1.0.0")]
        assert _check("1.0.0rc11.dev85+gabc1234", releases=releases).latest == "1.0.0"
        candidates_only = [_release("v1.0.0-rc.11", prerelease=True)]
        assert _check("1.0.0rc10.dev85", releases=candidates_only).status == "current"

    def test_asset_releases_and_the_rolling_nightly_are_not_app_releases(self):
        junk = [_release("music-v9"), _release("models-v3"), _release("nightly"), _release("v2")]
        assert _check("1.0.0", releases=junk).status == "current"

    def test_the_answer_links_that_releases_notes(self):
        offered = _check("0.9.0")
        assert offered.notes_url == (
            "https://github.com/sam-dumont/immich-memories/releases/tag/v1.0.0"
        )


class TestInstallMethod:
    def test_kubernetes_wins_over_docker(self):
        env = {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}
        assert detect_install_method(env=env, exists=lambda _: True, in_source_tree=False) == (
            "kubernetes"
        )

    def test_a_container_without_kubernetes_is_docker(self):
        method = detect_install_method(
            env={}, exists=lambda path: path == "/.dockerenv", in_source_tree=False
        )
        assert method == "docker"

    def test_a_package_install_is_pip_and_a_checkout_is_unknown(self):
        assert detect_install_method(env={}, exists=lambda _: False, in_source_tree=False) == "pip"
        assert detect_install_method(env={}, exists=lambda _: False, in_source_tree=True) == (
            "unknown"
        )

    @pytest.mark.parametrize(
        ("method", "expected"),
        [
            ("docker", "docker compose pull && docker compose up -d"),
            ("kubernetes", "ghcr.io/sam-dumont/immich-memories:1.0.1"),
            ("pip", 'immich-memories[all]==1.0.1"'),
        ],
    )
    def test_each_method_gets_its_own_command(self, method, expected):
        assert expected in (update_command(method, "1.0.1", platform="linux") or "")

    def test_the_pip_command_pins_a_candidate_the_way_python_writes_it(self):
        command = update_command("pip", "1.0.1-rc.2", platform="linux")
        assert 'immich-memories[all]==1.0.1rc2"' in command

    def test_an_unknown_install_has_no_command_only_the_docs(self):
        offered = check_for_update("0.9.0", "unknown", _client())
        assert offered.command is None
        assert offered.docs_url.endswith("/run/maintenance/upgrading")


class TestRequest:
    @pytest.mark.feature("updates.check")
    def test_one_unauthenticated_get_carries_no_version_id_or_config_value(self):
        seen: list[httpx.Request] = []
        check_for_update("0.9.123rc7", "docker", _client(seen=seen))

        assert len(seen) == 1
        request = seen[0]
        assert request.method == "GET"
        assert request.url.host == "api.github.com"
        assert request.url.path == "/repos/sam-dumont/immich-memories/releases"
        assert request.headers["user-agent"] == "immich-memories"
        wire = f"{request.url} {dict(request.headers)} {request.content!r}".lower()
        assert "0.9.123" not in wire
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers

    def test_a_network_failure_says_it_could_not_check_and_why(self):
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("secret-host.example refused", request=request)

        client = update_check.release_client(httpx.MockTransport(refuse))
        failed = check_for_update("1.0.0", "pip", client)
        assert failed.status == "failed"
        assert "could not reach github" in failed.reason.lower()
        assert "secret-host" not in failed.reason

    def test_an_error_status_and_a_garbled_answer_fail_without_a_traceback(self):
        assert "403" in check_for_update("1.0.0", "pip", _client(status=403)).reason
        garbled = update_check.release_client(
            httpx.MockTransport(lambda _: httpx.Response(200, text="<html>"))
        )
        assert check_for_update("1.0.0", "pip", garbled).status == "failed"
        with pytest.raises(UpdateCheckFailed):
            update_check.fetch_release_tags(_client(releases={"message": "no"}))


class TestDailyCheck:
    NOW = datetime(2030, 1, 10, 12, 0, tzinfo=UTC)

    def test_off_by_default_nothing_goes_out(self, tmp_path):
        seen: list = []
        config = _config(tmp_path, on=False)
        assert daily_update_status(config, "0.9.0", _client(seen=seen), now=self.NOW) is None
        assert seen == []

    @pytest.mark.feature("updates.daily")
    def test_on_it_asks_once_a_day_and_answers_from_the_store_in_between(self, tmp_path):
        seen: list = []
        config = _config(tmp_path, on=True)
        first = daily_update_status(config, "0.9.0", _client(seen=seen), now=self.NOW)
        later = daily_update_status(
            config, "0.9.0", _client(seen=seen), now=self.NOW + timedelta(hours=23)
        )
        tomorrow = daily_update_status(
            config, "0.9.0", _client(seen=seen), now=self.NOW + timedelta(hours=25)
        )

        assert first.latest == later.latest == tomorrow.latest == "1.0.0"
        assert len(seen) == 2

    def test_the_cached_answer_follows_the_running_version(self, tmp_path):
        config = _config(tmp_path, on=True)
        daily_update_status(config, "0.9.0", _client(), now=self.NOW)
        upgraded = daily_update_status(config, "1.0.0", _client(), now=self.NOW)
        assert upgraded.status == "current"

    def test_a_failed_day_is_not_retried_until_tomorrow_and_shows_no_banner(self, tmp_path):
        seen: list = []
        config = _config(tmp_path, on=True)
        down = _client(status=500, seen=seen)
        assert daily_update_status(config, "0.9.0", down, now=self.NOW) is None
        assert daily_update_status(config, "0.9.0", down, now=self.NOW) is None
        assert len(seen) == 1


class TestWebRoutes:
    def test_the_button_route_checks_now_and_the_daily_route_stays_quiet_when_off(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(update_check, "__version__", "0.9.0")
        monkeypatch.setattr(update_check, "release_client", lambda: _client())
        client = api_client(_config(tmp_path))

        checked = client.get("/api/v1/updates").json()
        quiet = client.get("/api/v1/updates/daily")

        assert (checked["status"], checked["latest"]) == ("available", "1.0.0")
        assert quiet.status_code == 200
        assert quiet.json() is None

    def test_the_daily_route_answers_when_the_setting_is_on(self, tmp_path, monkeypatch):
        monkeypatch.setattr(update_check, "__version__", "0.9.0")
        monkeypatch.setattr(update_check, "release_client", lambda: _client())
        client = api_client(_config(tmp_path, on=True))

        assert client.get("/api/v1/updates/daily").json()["latest"] == "1.0.0"


class TestCli:
    def _run(self, monkeypatch, args, releases=RELEASES, running="0.9.0", status=200):
        from immich_memories.cli import main

        monkeypatch.setattr(update_check, "__version__", running)
        monkeypatch.setattr(
            update_check, "release_client", lambda: _client(releases, status=status)
        )
        monkeypatch.setattr(update_check, "installed_via", lambda: "docker")
        return CliRunner().invoke(main, args)

    @pytest.mark.feature("updates.check")
    def test_version_check_names_the_release_the_notes_and_the_command(self, monkeypatch):
        result = self._run(monkeypatch, ["version", "--check"])
        assert result.exit_code == 0, result.output
        assert "1.0.0 is out" in result.output
        assert "releases/tag/v1.0.0" in result.output
        assert "docker compose pull && docker compose up -d" in result.output

    def test_version_check_says_when_you_are_up_to_date(self, monkeypatch):
        result = self._run(monkeypatch, ["version", "--check"], running="1.0.0")
        assert "up to date" in result.output.lower()

    def test_version_check_failure_is_a_sentence_not_a_traceback(self, monkeypatch):
        result = self._run(monkeypatch, ["version", "--check"], status=500)
        assert "could not check" in result.output.lower()
        assert "Traceback" not in result.output
        assert result.exit_code == 1

    def test_plain_version_prints_the_version_and_goes_nowhere(self, monkeypatch):
        def refuse():
            raise AssertionError("a plain version must not call out")

        from immich_memories.cli import main

        monkeypatch.setattr(update_check, "release_client", refuse)
        result = CliRunner().invoke(main, ["version"])
        assert result.exit_code == 0
        assert update_check.__version__ in result.output


def test_the_run_log_gets_one_line_when_the_daily_check_finds_a_release(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(update_check, "__version__", "0.9.0")
    monkeypatch.setattr(update_check, "release_client", lambda: _client())
    config = _config(tmp_path, on=True)

    with caplog.at_level("INFO"):
        update_check.log_daily_update_notice(config)

    lines = [r.getMessage() for r in caplog.records if "1.0.0 is out" in r.getMessage()]
    assert len(lines) == 1
    assert json.dumps(lines)  # one plain line
