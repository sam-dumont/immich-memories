"""Settings → People on the hermetic launch: the roster, the answers, and no reloads (#824, S7).

The roster the page shows comes from the store the launch workspace's config names,
never the developer's own: the test imports the roster into that same store itself
and checks the names it wrote are the names on the page.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from immich_memories.db import Store
from immich_memories.people.companion import load_document
from immich_memories.people.transfer import import_document

pytestmark = pytest.mark.e2e

_ROSTER = 34
_PAGE = 30


def _entry(index: int) -> dict:
    return {
        "ids": [f"fake-person-{index:02d}"],
        "name": f"Fixture Person {index:02d}",
        "birth_date": None,
        "inferred": {
            "tier": "inner" if index < 4 else "recurring",
            "counts_reliable": True,
            "evidence": {
                "count": 400 - index,
                "active_months": 12,
                "first_month": "2019-01",
                "last_month": "2021-06",
                "span_years": 2.4,
                "onset": "2019-03",
                "concentration": 8.3,
                "continuity": 0.4,
            },
            "links": [],
        },
        "confirmed": {"role": None, "links": [], "notes": None},
    }


def _seed_people(launch_workspace) -> Store:
    """The launched app's store, holding the fixture roster."""
    store = launch_workspace.store()
    roster = {"version": 1, "people": [_entry(index) for index in range(_ROSTER)]}
    import_document(store, roster, replace=True)
    return store


def _cards(page: Page):
    return page.get_by_role("listitem").filter(has=page.get_by_label("Notes"))


def _open_people(page: Page, launch_app_url: str, launch_workspace) -> Store:
    store = _seed_people(launch_workspace)
    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_url("**/app/settings/people")
    expect(_cards(page).first).to_be_visible(timeout=30_000)
    return store


def _scrolled(page: Page) -> float:
    """How far the page is scrolled: the app shell scrolls its own pane, not the window."""
    return page.evaluate(
        "() => { let pane = document.querySelector('main');"
        " while (pane && pane.scrollTop === 0) pane = pane.parentElement;"
        " return pane ? pane.scrollTop : window.scrollY; }"
    )


def _saved(page: Page, person_id: str):
    return page.expect_response(
        lambda response: (
            response.request.method == "PUT"
            and response.url.endswith(f"/api/v1/roster/{person_id}")
        )
    )


def test_the_roster_reads_the_workspace_store_a_page_at_a_time(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    _open_people(page, launch_app_url, launch_workspace)

    expect(_cards(page)).to_have_count(_PAGE)
    expect(_cards(page).first).to_contain_text("Fixture Person 00")
    assert page.locator('img[src^="data:"]').count() == 0, "no face is inlined as a data URI"
    faces = page.locator('img[src^="/api/v1/people/"]')
    expect(faces).to_have_count(_PAGE)
    expect(faces.first).to_have_js_property("naturalWidth", 128, timeout=15_000)

    page.get_by_role("button", name="Show more").click()

    expect(_cards(page)).to_have_count(_ROSTER)
    expect(_cards(page).last).to_contain_text("Fixture Person 33")
    expect(page.get_by_role("button", name="Show more")).to_have_count(0)


def test_a_role_and_a_note_are_saved_without_reloading_the_page(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    store = _open_people(page, launch_app_url, launch_workspace)
    page.evaluate("window.__s7_same_document = true")
    page.get_by_role("button", name="Show more").click()
    last = _cards(page).last
    expect(last).to_contain_text("Fixture Person 33")
    last.scroll_into_view_if_needed()
    assert _scrolled(page) > 0

    with _saved(page, "fake-person-33"):
        last.get_by_label("Role", exact=False).fill("godparent")
        last.get_by_label("Role", exact=False).press("Tab")
    with _saved(page, "fake-person-33"):
        last.get_by_label("Notes").fill("lives abroad")
        last.get_by_label("Notes").press("Tab")

    assert page.evaluate("window.__s7_same_document") is True, "the page was reloaded"
    assert _scrolled(page) > 0, "the page lost its place"
    expect(_cards(page)).to_have_count(_ROSTER)
    expect(last.get_by_label("Role", exact=False)).to_have_value("godparent")
    saved = load_document(store)
    person = next(entry for entry in saved["people"] if entry["ids"] == ["fake-person-33"])
    assert person["confirmed"]["role"] == "godparent"
    assert person["confirmed"]["notes"] == "lives abroad"


def test_adding_a_person_redraws_the_roster_in_place(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    store = _open_people(page, launch_app_url, launch_workspace)
    page.evaluate("window.__s7_same_document = true")

    page.get_by_label("Full name").fill("Off Camera Uncle")
    page.get_by_role("button", name="Add someone not in Immich").click()
    expect(page.get_by_label("Full name")).to_have_value("")

    page.get_by_label("Find a name").fill("off camera")
    expect(_cards(page)).to_have_count(1)
    expect(_cards(page).first).to_contain_text("Off Camera Uncle")
    assert page.evaluate("window.__s7_same_document") is True, "the page was reloaded"
    saved = load_document(store)
    assert any(entry["name"] == "Off Camera Uncle" for entry in saved["people"])


def _twin(index: int, name: str, other: int) -> dict:
    entry = _entry(index)
    entry["name"] = name
    entry["inferred"]["links"] = [
        {"kind": "twin", "with": f"fake-person-{other:02d}", "confidence": 0.9, "via": "birth-date"}
    ]
    return entry


def test_each_curation_flag_names_both_people_and_can_be_kept_apart(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    store = launch_workspace.store()
    pairs = [
        (_twin(0, "Robin Twin", 1), _twin(1, "Remy Twin", 0)),
        (_twin(2, "Ana Twin", 3), _twin(3, "Alma Twin", 2)),
    ]
    people = [person for pair in pairs for person in pair]
    import_document(store, {"version": 1, "people": people}, replace=True)

    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded", timeout=30_000)
    flags = page.get_by_test_id("curation-flag")
    expect(flags).to_have_count(2, timeout=30_000)
    expect(flags.nth(0)).to_contain_text("Robin Twin")
    expect(flags.nth(0)).to_contain_text("Remy Twin")
    expect(flags.nth(1)).to_contain_text("Ana Twin")
    expect(flags.nth(1)).to_contain_text("Alma Twin")
    expect(flags.nth(0)).not_to_contain_text("—")
    expect(
        page.get_by_role("navigation", name="Main navigation")
        .get_by_role("link", name="People")
        .first
    ).to_be_visible()

    flags.nth(0).get_by_role("button", name="Keep apart").click()

    expect(flags).to_have_count(1)
    expect(flags.first).to_contain_text("Ana Twin")


def test_a_late_roster_refresh_cannot_undo_a_newer_saved_note(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    _open_people(page, launch_app_url, launch_workspace)
    delayed = []

    # WHY: delay one real HTTP response to reproduce a slow earlier refresh;
    # both saves and roster reads still use the launched app and disposable store.
    def hold_first_refresh(route):
        if not delayed:
            delayed.append(route)
        else:
            route.continue_()

    page.route("**/api/v1/roster", hold_first_refresh)
    with page.expect_request("**/api/v1/roster"):
        _cards(page).first.get_by_label("Role", exact=False).fill("friend")
        _cards(page).first.get_by_label("Role", exact=False).press("Tab")
    response = page.request.get(f"{launch_app_url}/api/v1/roster")
    assert response.ok
    assert len(delayed) == 1

    note = _cards(page).nth(1).get_by_label("Notes")
    with page.expect_response("**/api/v1/roster"):
        note.fill("visits in summer")
        note.press("Tab")
    expect(note).to_have_value("visits in summer")

    with page.expect_response("**/api/v1/roster"):
        delayed[0].fulfill(response=response)
    page.wait_for_load_state("networkidle")

    expect(note).to_have_value("visits in summer")


def test_a_failed_roster_refresh_keeps_the_save_and_offers_a_retry(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    _open_people(page, launch_app_url, launch_workspace)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # WHY: fail only the roster read at the HTTP boundary; the save is real.
    page.route(
        "**/api/v1/roster",
        lambda route: route.fulfill(status=503, json={"detail": "Temporarily unavailable"}),
    )
    note = _cards(page).first.get_by_label("Notes")
    with page.expect_response("**/api/v1/roster"):
        note.fill("visits in summer")
        note.press("Tab")
    page.wait_for_load_state("networkidle")

    assert errors == [], "a failed refresh must not reject outside the page's error handling"
    expect(note).to_have_value("visits in summer")
    expect(page.get_by_role("alert")).to_have_text("Could not load people.")

    page.unroute("**/api/v1/roster")
    page.get_by_role("button", name="Try again").click()

    expect(page.get_by_role("alert")).to_have_count(0)
    expect(note).to_have_value("visits in summer")
    assert errors == []
