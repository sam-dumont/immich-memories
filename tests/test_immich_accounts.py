"""Extra Immich accounts (#1500 slice 2): the config shape, their secrets and the opener.

Synthetic servers and keys only. The primary `immich.url` / `immich.api_key` stays the
upload target; an extra account is a named connection nobody reads until a run selects it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from immich_memories.api.accounts import AccountUnavailable, open_accounts
from immich_memories.cli import main
from immich_memories.config_loader import Config, set_config
from immich_memories.config_models import ImmichConfig
from immich_memories.logging_config import SecretRedactionFilter
from immich_memories.preflight import CheckStatus, run_preflight_checks

URL = "https://immich.example.test"
PRIMARY_KEY = "primary-" * 4
PARTNER_KEY = "partner-" * 4


def test_an_extra_account_loads_from_the_immich_section(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "immich:\n"
        f"  url: {URL}\n"
        f"  api_key: {PRIMARY_KEY}\n"
        "  accounts:\n"
        "    partner:\n"
        f"      url: {URL}\n"
        f"      api_key: {PARTNER_KEY}\n"
    )

    config = Config.from_yaml(path)

    assert config.immich.api_key == PRIMARY_KEY
    partner = config.immich.accounts["partner"]
    assert (partner.url, partner.api_key, partner.api_version.value) == (URL, PARTNER_KEY, "auto")


@pytest.mark.parametrize("name", ["primary", "", "Partner", "has space", "a__b", "-x"])
def test_an_account_name_that_cannot_be_an_alias_key_is_refused(name: str):
    with pytest.raises(ValidationError, match="account name"):
        Config(immich={"accounts": {name: {"url": URL, "api_key": PARTNER_KEY}}})


def test_an_extra_accounts_key_can_come_from_the_environment(tmp_path: Path, monkeypatch):
    """The file names the account and its server; the key stays out of the file."""
    monkeypatch.setenv("IMMICH_MEMORIES_IMMICH__ACCOUNTS__PARTNER__API_KEY", PARTNER_KEY)
    monkeypatch.setenv("IMMICH_MEMORIES_IMMICH__ACCOUNTS__GRANDMA__URL", URL)
    monkeypatch.setenv("IMMICH_MEMORIES_IMMICH__ACCOUNTS__GRANDMA__API_KEY", PRIMARY_KEY)
    path = tmp_path / "config.yaml"
    path.write_text(f"immich:\n  accounts:\n    partner:\n      url: {URL}\n")

    accounts = Config.from_yaml(path).immich.accounts

    assert (accounts["partner"].url, accounts["partner"].api_key) == (URL, PARTNER_KEY)
    assert (accounts["grandma"].url, accounts["grandma"].api_key) == (URL, PRIMARY_KEY)


def test_an_extra_accounts_key_is_redacted_from_logs():
    set_config(Config(immich={"accounts": {"partner": {"url": URL, "api_key": PARTNER_KEY}}}))
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "with %s", (PARTNER_KEY,), None)

    SecretRedactionFilter().filter(record)

    assert PARTNER_KEY not in record.getMessage()
    set_config(None)


# --- the opener ------------------------------------------------------------------------

DOWN_URL = "https://down.example.test"
GRANDMA_KEY = "grandma-" * 4
USERS = {PRIMARY_KEY: "user-primary", PARTNER_KEY: "user-partner", GRANDMA_KEY: "user-grandma"}


@pytest.fixture
def immich_server(monkeypatch) -> list[httpx.Request]:
    """One fake Immich server that answers /users/me for the keys it knows."""
    seen: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "down.example.test":
            raise httpx.ConnectError("connection refused", request=request)
        user = USERS.get(request.headers["x-api-key"])
        if user is None:
            return httpx.Response(401, json={"message": "Invalid API key"})
        return httpx.Response(200, json={"id": user, "email": f"{user}@example.test"})

    # WHY: the HTTP boundary; every Immich request goes to the in-process fake server above.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return seen


def _household(**extra: dict) -> ImmichConfig:
    accounts = {
        "partner": {"url": URL, "api_key": PARTNER_KEY, "api_version": "v2"},
        "grandma": {"url": URL, "api_key": GRANDMA_KEY, "api_version": "v2"},
    }
    return ImmichConfig(url=URL, api_key=PRIMARY_KEY, api_version="v2", accounts=accounts | extra)


def test_each_selected_account_is_opened_and_proves_who_it_is(immich_server):
    opened = open_accounts(_household(), ["primary", "partner"])

    assert {name: account.user.id for name, account in opened.items()} == {
        "primary": "user-primary",
        "partner": "user-partner",
    }
    assert GRANDMA_KEY not in {request.headers["x-api-key"] for request in immich_server}
    for account in opened.values():
        account.client.close()


def test_an_unknown_account_fails_before_any_request(immich_server):
    with pytest.raises(AccountUnavailable, match="'uncle' is not configured"):
        open_accounts(_household(), ["partner", "uncle"])

    assert immich_server == []


def test_an_account_whose_key_is_refused_is_named_without_its_key(immich_server):
    wrong = "wrong-key-" * 4
    household = _household(partner={"url": URL, "api_key": wrong, "api_version": "v2"})

    with pytest.raises(AccountUnavailable, match="'partner' rejected its API key") as refused:
        open_accounts(household, ["primary", "partner"])

    assert wrong not in str(refused.value)


def test_an_unreachable_account_fails_the_open(immich_server, monkeypatch):
    # WHY: the client's retry backoff is real sleep; the retries still happen, just instantly.
    monkeypatch.setattr("immich_memories.api.immich._BACKOFF_BASE", 0.0)
    household = _household(grandma={"url": DOWN_URL, "api_key": GRANDMA_KEY, "api_version": "v2"})

    with pytest.raises(AccountUnavailable, match="'grandma' failed: Request failed"):
        open_accounts(household, ["grandma"])


def test_config_test_checks_every_extra_account_on_its_own_line(immich_server, tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        f"immich:\n  url: {URL}\n  api_key: {PRIMARY_KEY}\n  api_version: v2\n"
        "  accounts:\n"
        f"    partner:\n      url: {URL}\n      api_key: {PARTNER_KEY}\n      api_version: v2\n"
        f"    grandma:\n      url: {URL}\n      api_key: wrong-{GRANDMA_KEY}\n"
        "      api_version: v2\n"
    )

    result = CliRunner().invoke(main, ["--config", str(path), "config", "test"])

    lines = result.output.splitlines()
    assert any("partner" in line and "user-partner" in line for line in lines)
    assert any("grandma" in line and "rejected its API key" in line for line in lines)
    assert not any(key in result.output for key in (PRIMARY_KEY, PARTNER_KEY, GRANDMA_KEY))
    assert result.exit_code == 1


def test_preflight_lists_each_extra_account(immich_server):
    config = Config(immich=_household().model_dump())

    checks = {check.name: check for check in run_preflight_checks(config)}

    assert checks["Immich account partner"].status is CheckStatus.OK
    assert checks["Immich account grandma"].message == "Connected as user-grandma@example.test"


def test_an_account_without_a_key_is_refused_before_any_request(immich_server):
    household = _household(partner={"url": URL})

    with pytest.raises(AccountUnavailable, match="'partner' needs both a url and an api_key"):
        open_accounts(household, ["partner"])

    assert immich_server == []
