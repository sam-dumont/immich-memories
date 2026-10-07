"""Settings > People: who owns the library, one row per pair, and what an empty page says."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from immich_memories.people.companion import load_document
from immich_memories.people.transfer import import_document

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
    people = [_entry(0, "Ana Example", _dyad(1)), _entry(1, "Luc Sample", _dyad(0))]
    import_document(store, {"version": 1, "people": people}, replace=True)

    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded", timeout=30_000)
    ana = _card(page, "Ana Example")
    expect(ana.get_by_test_id("relationship-row")).to_have_count(1, timeout=30_000)
    expect(ana.get_by_test_id("relationship-row")).to_contain_text("Looks linked to Luc Sample")

    ana.get_by_label("What is Ana Example to Luc Sample?").select_option(label="parent of")

    row = ana.get_by_test_id("relationship-row")
    expect(row).to_have_count(1)
    expect(row).to_have_attribute("data-status", "named")
    expect(row).to_contain_text("parent of")
    luc = _card(page, "Luc Sample").get_by_test_id("relationship-row")
    expect(luc).to_have_count(1)
    expect(luc).to_contain_text("child of")


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
