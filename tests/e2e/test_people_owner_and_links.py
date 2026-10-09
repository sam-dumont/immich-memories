"""Settings > People: who owns the library, one row per pair, and what an empty page says."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from immich_memories.people.companion import load_document
from immich_memories.people.transfer import import_document
from tests.e2e.web_flow import evidence

pytestmark = pytest.mark.e2e


def _entry(index: int, name: str, links: list[dict] | None = None) -> dict:
    return {
        "ids": [f"fake-person-{index:02d}"],
        "name": name,
        "birth_date": None,
        "inferred": {
            "tier": "inner",
            "counts_reliable": True,
            "evidence": {"count": 300 - index, "active_months": 12, "first_month": "2019-01"},
            "links": links or [],
        },
        "confirmed": {"role": None, "links": [], "notes": None},
    }


def _dyad(other: int) -> list[dict]:
    return [
        {
            "kind": "tight-dyad",
            "with": f"fake-person-{other:02d}",
            "confidence": 0.8,
            "via": "co-occurrence",
        }
    ]


def _card(page: Page, name: str):
    return page.get_by_role("listitem").filter(has=page.locator("p.font-semibold", has_text=name))


def test_the_owner_is_a_guess_until_somebody_picks_and_a_scan_keeps_the_pick(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    store = launch_workspace.store()
    document = {
        "version": 1,
        "owner": {"person_id": "fake-person-00", "name": "Ana Example", "identified": "inferred"},
        "people": [_entry(0, "Ana Example"), _entry(1, "Luc Sample")],
    }
    import_document(store, document, replace=True)

    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded", timeout=30_000)
    owner = page.get_by_test_id("owner-row")
    expect(owner.get_by_test_id("owner-name")).to_have_text("Ana Example", timeout=30_000)
    expect(owner).to_contain_text("a guess")

    owner.get_by_label("Choose the owner").select_option(label="Luc Sample")

    expect(owner.get_by_test_id("owner-name")).to_have_text("Luc Sample", timeout=15_000)
    expect(owner).to_contain_text("you confirmed it")
    saved = load_document(store)
    assert saved["owner"]["person_id"] == "fake-person-01"
    assert saved["owners"]["primary"] == {"person_id": "fake-person-01", "identified": "confirmed"}

    owner.get_by_label("Choose the owner").select_option(label="Nobody in this library")
    expect(owner.get_by_test_id("owner-name")).to_have_text("Nobody in this library")
    assert load_document(store)["owner"] is None


def test_a_detected_link_is_one_row_and_naming_it_leaves_one_row_on_each_side(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    store = launch_workspace.store()
    people = [_entry(0, "Ana Example", _dyad(31)), _entry(31, "Luc Sample", _dyad(0))]
    people.extend(_entry(index, f"Person {index}") for index in range(1, 30))
    import_document(store, {"version": 1, "people": people}, replace=True)

    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded", timeout=30_000)
    ana = _card(page, "Ana Example")
    expect(page.get_by_role("combobox", name="What is", exact=False)).to_have_count(
        1, timeout=30_000
    )
    expect(ana.get_by_test_id("relationship-row")).to_have_count(1, timeout=30_000)
    expect(ana.get_by_test_id("relationship-row")).to_contain_text("Looks linked to Luc Sample")

    page.get_by_role("textbox", name="Find a name").fill("Luc")
    expect(page.get_by_label("What is Luc Sample to Ana Example?")).to_be_visible()
    page.get_by_role("textbox", name="Find a name").clear()
    ana.get_by_label("What is Ana Example to Luc Sample?").select_option(label="parent of")

    row = ana.get_by_test_id("relationship-row")
    expect(row).to_have_count(1)
    expect(row).to_have_attribute("data-status", "named")
    expect(row).to_contain_text("parent of")
    page.get_by_role("button", name="Show more").click()
    luc = _card(page, "Luc Sample").get_by_test_id("relationship-row")
    expect(luc).to_have_count(1)
    expect(luc).to_contain_text("child of")
    expect(page.get_by_role("combobox", name="What is", exact=False)).to_have_count(0)

    luc.get_by_role("button", name="Remove this relationship").click()
    expect(page.locator('[data-testid="relationship-row"][data-status="named"]')).to_have_count(0)
    expect(page.get_by_role("combobox", name="What is", exact=False)).to_have_count(1)
    ana.get_by_role("button", name="No, they are not").click()
    expect(page.get_by_role("combobox", name="What is", exact=False)).to_have_count(0)
    expect(ana.get_by_test_id("relationship-row")).to_have_attribute("data-status", "rejected")
    expect(luc).to_have_count(0)


def test_a_link_confirmed_in_an_older_release_reads_as_not_named(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    store = launch_workspace.store()
    ana = _entry(0, "Ana Example", _dyad(1))
    ana["confirmed"]["links"] = [
        {"kind": "tight-dyad", "with": "fake-person-01", "decision": "confirmed"}
    ]
    import_document(
        store, {"version": 1, "people": [ana, _entry(1, "Luc Sample", _dyad(0))]}, replace=True
    )

    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded", timeout=30_000)

    for name in ("Ana Example", "Luc Sample"):
        row = _card(page, name).get_by_test_id("relationship-row")
        expect(row).to_have_count(1, timeout=30_000)
        expect(row).to_contain_text("relationship not named")


def test_an_unscanned_library_says_what_it_is_waiting_for_and_offers_the_scan(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    import_document(launch_workspace.store(), {"version": 1, "people": []}, replace=True)

    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded", timeout=30_000)

    empty = page.get_by_test_id("nobody-yet")
    expect(empty).to_contain_text("filled the first time a library is prepared", timeout=30_000)
    expect(empty).to_contain_text("New memory reads Immich directly")
    expect(empty.get_by_role("button", name="Rescan now")).to_be_enabled()


def test_an_unknown_owner_explains_the_account_name_match(
    page: Page, launch_app_url: str, launch_workspace
):
    import_document(
        launch_workspace.store(), {"version": 1, "people": [_entry(0, "Ana Example")]}, replace=True
    )
    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded")
    owner = page.get_by_test_id("owner-row")
    expect(owner).to_contain_text(
        "The API key's account name has not been matched to a named person."
    )
    expect(owner).to_contain_text("Choose the owner, or name people in Immich and rescan.")
    evidence(page, "unknown-owner")
    owner.get_by_label("Choose the owner").select_option(label="Ana Example")
    expect(owner).not_to_contain_text("has not been matched")


def test_a_successful_scan_refreshes_the_owner_and_keeps_a_saved_choice_without_reloading(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    store = launch_workspace.store()
    import_document(store, {"version": 1, "people": []}, replace=True)
    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded", timeout=30_000)
    owner = page.get_by_test_id("owner-row")
    expect(owner.get_by_test_id("owner-name")).to_have_text("not known yet", timeout=30_000)
    choices = owner.get_by_label("Choose the owner")
    expect(choices.locator("option")).to_have_count(2)
    page.evaluate("window.__owner_scan_same_document = true")

    with page.expect_response("**/api/v1/roster", timeout=60_000):
        page.get_by_role("button", name="Rescan now").click()

    expect(page.get_by_role("region", name="Progress")).to_contain_text("Done.")
    expect(_card(page, "Robin")).to_be_visible()
    evidence(page, "owner-after-first-scan")
    expect(choices.get_by_role("option", name="Robin", exact=True)).to_have_count(1)
    expect(owner.get_by_test_id("owner-name")).not_to_have_text("not known yet")
    assert page.evaluate("window.__owner_scan_same_document") is True

    choices.select_option(label="Robin")
    expect(owner.get_by_test_id("owner-name")).to_have_text("Robin")
    expect(owner).to_contain_text("you confirmed it")
    with (
        page.expect_response("**/api/v1/roster", timeout=60_000),
        page.expect_response("**/api/v1/roster/owners", timeout=60_000),
    ):
        page.get_by_role("button", name="Rescan the library").click()

    expect(owner.get_by_test_id("owner-name")).to_have_text("Robin")
    expect(owner).to_contain_text("you confirmed it")
    assert load_document(store)["owners"]["primary"]["person_id"] == "person-robin"
    assert page.evaluate("window.__owner_scan_same_document") is True
    evidence(page, "owner-confirmed-after-rescan")
