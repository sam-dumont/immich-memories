"""Link a person across two accounts by picking them, save a group, pick it on the brief (#1500, #2235).

A second Immich account (`immich.accounts.partner`) is configured for this launch only, so the
account scope and the per-account alias form show up — most launches have one account, and both
stay hidden then. The fake Immich server backs both names; a real second account works the same.
"""

from __future__ import annotations

import re
from collections.abc import Generator

import pytest
import yaml
from playwright.sync_api import Page, expect

from immich_memories.people.transfer import import_document
from tests.e2e.conftest import LaunchWorkspace, _launch_workspace, _serve_launch
from tests.e2e.fake_immich import FakeImmichServer

pytestmark = pytest.mark.e2e

_PERSON_ID = "fake-person-01"


@pytest.fixture(scope="module")
def accounts_workspace(tmp_path_factory, fake_immich_server: FakeImmichServer) -> LaunchWorkspace:
    """A launch workspace with a second Immich account, `partner`, next to the primary one."""
    workspace = _launch_workspace(tmp_path_factory.mktemp("accounts"), fake_immich_server)
    config = yaml.safe_load(workspace.config_path.read_text())
    config["immich"]["accounts"] = {
        "partner": {
            "url": fake_immich_server.base_url,
            "api_key": fake_immich_server.partner_api_key,
        }
    }
    workspace.config_path.write_text(yaml.safe_dump(config))
    store = workspace.store()
    import_document(
        store,
        {
            "version": 1,
            "people": [
                {
                    "ids": [_PERSON_ID],
                    "name": "Fixture Person 01",
                    "birth_date": None,
                    "inferred": {
                        "tier": "inner",
                        "counts_reliable": True,
                        "evidence": {
                            "count": 40,
                            "active_months": 6,
                            "first_month": "2024-01",
                            "last_month": "2024-06",
                            "span_years": 0.5,
                            "onset": "2024-01",
                            "concentration": 8.3,
                            "continuity": 0.4,
                        },
                        "links": [],
                    },
                    "confirmed": {"role": None, "links": [], "notes": None},
                }
            ],
        },
        replace=True,
    )
    return workspace


@pytest.fixture(scope="module")
def accounts_app_url(
    accounts_workspace: LaunchWorkspace, unused_tcp_port_factory
) -> Generator[str, None, None]:
    yield from _serve_launch(accounts_workspace, unused_tcp_port_factory(), models_fetched=True)


def test_link_a_person_by_picking_save_a_group_pick_it_on_the_brief(
    page: Page, accounts_app_url: str
) -> None:
    page.goto(
        f"{accounts_app_url}/app/settings/people", wait_until="domcontentloaded", timeout=30_000
    )
    card = page.get_by_role("listitem").filter(
        has=page.locator("p.font-semibold", has_text="Fixture Person 01")
    )
    expect(card).to_be_visible(timeout=30_000)

    # The partner account holds a person with the same name: offered first, one click to link.
    card.get_by_text("Link a person from partner").click()
    suggestion = card.get_by_test_id("link-suggestion")
    expect(suggestion).to_contain_text("Same person as Fixture Person 01?", timeout=15_000)
    suggestion.get_by_role("button", name="Link", exact=True).click()
    linked = card.get_by_test_id("account-link")
    expect(linked.get_by_text("Fixture Person 01", exact=True)).to_be_visible(timeout=15_000)
    expect(linked.get_by_role("link", name="Open in Immich")).to_have_attribute(
        "href", re.compile(r"/people/partner-person-01$")
    )

    # Save a group by picking the person, no ids typed.
    page.get_by_label("Label", exact=True).fill("kids")
    page.get_by_label("Pick the people", exact=True).select_option(_PERSON_ID)
    page.get_by_role("button", name="Save group", exact=True).click()
    saved = page.get_by_role("listitem").filter(has=page.get_by_text("kids", exact=True))
    expect(saved).to_be_visible(timeout=15_000)
    expect(saved).to_contain_text("Fixture Person 01")

    # On the brief, pick the group and both accounts; the shown command carries both.
    page.goto(f"{accounts_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
    expect(page.get_by_role("button", name="kids", exact=False)).to_be_visible(timeout=15_000)
    with page.expect_response(lambda r: r.url.endswith("/api/v1/cuts/command")):
        page.get_by_role("button", name="kids", exact=False).click()
    for name in ("primary", "partner"):
        with page.expect_response(lambda r: r.url.endswith("/api/v1/cuts/command")):
            page.get_by_text(name, exact=True).click()

    command = page.locator("code[aria-label='Command']")
    expect(command).to_contain_text("--group=kids")
    expect(command).to_contain_text("--accounts=primary,partner")


def test_a_person_declined_is_not_offered_again_and_a_link_can_be_undone(
    page: Page, accounts_app_url: str
) -> None:
    page.goto(
        f"{accounts_app_url}/app/settings/people", wait_until="domcontentloaded", timeout=30_000
    )
    card = page.get_by_role("listitem").filter(
        has=page.locator("p.font-semibold", has_text="Fixture Person 01")
    )
    # Earlier in this module the person was linked; take it back first.
    expect(card.get_by_test_id("account-link")).to_be_visible(timeout=30_000)
    unlink = card.get_by_role("button", name="Unlink")
    if unlink.count():
        unlink.click()
        expect(unlink).to_have_count(0, timeout=15_000)

    card.get_by_text("Link a person from partner").click()
    suggestion = card.get_by_test_id("link-suggestion")
    expect(suggestion).to_be_visible(timeout=15_000)
    suggestion.get_by_role("button", name="Not the same person").click()
    expect(suggestion).to_have_count(0, timeout=15_000)

    page.reload(wait_until="domcontentloaded")
    card = page.get_by_role("listitem").filter(
        has=page.locator("p.font-semibold", has_text="Fixture Person 01")
    )
    card.get_by_text("Link a person from partner").click()
    expect(card.get_by_label("Person in partner")).to_be_visible(timeout=15_000)
    expect(card.get_by_test_id("link-suggestion")).to_have_count(0)
