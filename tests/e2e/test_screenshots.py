"""Capture the web client for the docs, in light and dark.

Every frame comes from the hermetic launch -- the fake Immich service and the scripted
editorial route -- so nothing personal can reach a screenshot. Each theme is one pass through
the flow: the brief, the cut in progress, the review, an edit, the render, the pool, and the
pages around them. The files land in docs-site/static/img/screenshots/ under the names the docs
embed (a `dark-` prefix for the dark theme).

Usage:
    make screenshots          # light + dark, saves to docs-site/
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import set_theme
from tests.e2e.fake_library import CARRIERS, LIBRARY, THESIS
from tests.e2e.redaction import redact_page
from tests.e2e.web_flow import contact_sheet, cut_june, render, the_film

pytestmark = [pytest.mark.e2e, pytest.mark.visual]

_THEMES = ("light", "dark")
# The stock library's swim picture, as a nudity detector that misread it would bank it: the
# false positive the owner clears by hand. Seeded by the recipe, never placed by hand.
_HELD = "trip-swim-02"


def _name(base: str, theme: str) -> str:
    return f"dark-{base}" if theme == "dark" else base


def _settle(page: Page) -> None:
    """Park the pointer, wait for every visible picture, redact temp paths."""
    page.mouse.move(0, 0)
    # A default install has no Demo mode switch (`server.enable_demo_mode`); neither do the docs.
    page.evaluate(
        "document.querySelectorAll('[aria-label=\"Demo mode\"]').forEach(b => b.style.display = 'none')"
    )
    page.wait_for_function(
        # Only what the frame shows: a lazy thumbnail below the fold is never fetched.
        "() => [...document.images].filter(i => { const r = i.getBoundingClientRect();"
        " return r.height > 0 && r.bottom > 0 && r.top < innerHeight; }).every(i => i.complete)",
        timeout=30_000,
    )
    # WHY: the hermetic launch writes under a pytest temp root that carries the developer's
    # user name in its path; the redaction rewrites those lines and refuses a leaked address.
    redact_page(page)
    page.wait_for_timeout(300)


def _save(page: Page, directory: Path, name: str, *, full: bool = False) -> None:
    _settle(page)
    page.screenshot(path=str(directory / f"{name}.png"), full_page=full)


def _save_part(page: Page, locator, directory: Path, name: str) -> None:
    locator.scroll_into_view_if_needed()
    _settle(page)
    locator.screenshot(path=str(directory / f"{name}.png"))


def _open(page: Page, url: str, theme: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    set_theme(page, theme)


def _brief_for_june(page: Page) -> None:
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.get_by_label("Month", exact=True).select_option("6")
    page.get_by_text("Length and pictures").click()
    page.get_by_label("Length in minutes", exact=False).fill("2")


@pytest.mark.parametrize("theme", _THEMES)
def test_capture_memory_walkthrough(
    page: Page, launch_app_url: str, screenshot_dir: Path, theme: str
) -> None:
    """The brief, the cut, the review, an edit, the render: every frame the docs embed."""
    d = screenshot_dir
    _open(page, f"{launch_app_url}/app/create", theme)
    _brief_for_june(page)
    _save(page, d, _name("memory-brief", theme))
    page.get_by_label("Who may see it").select_option("just-us")
    _save(page, d, _name("memory-brief-sharing", theme))
    page.get_by_label("Who may see it").select_option("")

    page.get_by_role("button", name="Cut", exact=True).click()
    progress = page.get_by_role("region", name="Progress")
    expect(progress.get_by_text(re.compile(r"\d+ of \d+"))).to_be_visible(timeout=60_000)
    expect(
        progress.get_by_role("list", name="Pictures just read").locator("img").first
    ).to_be_visible()
    _save(page, d, _name("memory-cutting", theme))

    page.wait_for_url("**/app/runs/**", timeout=240_000)
    expect(page.get_by_text(THESIS)).to_be_visible()
    expect(contact_sheet(page)).to_have_count(len(CARRIERS))
    _save(page, d, _name("memory-story", theme))
    page.get_by_role("radio", name="Stories").click()
    _save(page, d, _name("memory-story-ranked", theme))
    page.get_by_role("radio", name="Contact sheet").click()

    # An edit: one picture out, one swapped for another of its moment, then kept as a revision.
    inspector = page.get_by_role("article", name="Picture review")
    contact_sheet(page).nth(1).click()
    inspector.get_by_role("button", name="Remove from this cut").click()
    swappable = next(
        (i for i in range(len(CARRIERS)) if i != 1 and _has_alternatives(page, i)), None
    )
    if swappable is not None:
        inspector.get_by_role("list", name="Other pictures of this moment").get_by_role(
            "button"
        ).first.click()
        inspector.get_by_role("button", name="Use this picture instead").click()
    _save(page, d, _name("memory-review-edit", theme))
    page.get_by_role("button", name="Save revision").click()
    expect(page.get_by_role("status").filter(has_text="Saved as revision")).to_be_visible()

    panel = page.get_by_role("region", name="Render")
    panel.scroll_into_view_if_needed()
    panel.get_by_label("What to render").select_option(label="Revision 1")
    _save_part(page, panel, d, _name("memory-options", theme))
    render(page, resolution="720p")
    expect(panel.get_by_role("progressbar")).to_be_visible(timeout=30_000)
    _save_part(page, panel, d, _name("memory-rendering", theme))
    expect(the_film(page)).to_be_visible(timeout=600_000)
    page.wait_for_function(
        "video => video.readyState >= 2", arg=the_film(page).element_handle(), timeout=60_000
    )
    _save_part(page, panel, d, _name("memory-export", theme))

    page.evaluate("window.scrollTo(0, 0)")
    page.get_by_role("navigation", name="Main navigation").first.evaluate(
        "nav => nav.style.display = 'none'"
    )
    _save(page, d, _name("hero-memory", theme))


def _has_alternatives(page: Page, index: int) -> bool:
    contact_sheet(page).nth(index).click()
    return (
        page.get_by_role("article", name="Picture review")
        .get_by_role("list", name="Other pictures of this moment")
        .count()
        > 0
    )


@pytest.mark.parametrize("theme", _THEMES)
def test_capture_trip_brief(
    page: Page, launch_app_url: str, screenshot_dir: Path, theme: str
) -> None:
    _open(page, f"{launch_app_url}/app/create", theme)
    page.get_by_text("Trip", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    trips = page.get_by_role("list", name="Trips").get_by_role("listitem")
    trips.filter(has_text="2024-06-21").click(timeout=60_000)
    _save(page, screenshot_dir, _name("memory-trip-brief", theme))


@pytest.mark.parametrize("theme", _THEMES)
def test_capture_the_pool_and_picture_decisions(
    page: Page, launch_app_url: str, launch_workspace, screenshot_dir: Path, theme: str
) -> None:
    """The pool's outcomes, a held picture and its clear dialog, and Never use (#1324)."""
    from immich_memories.store import owner_decisions
    from tests.e2e.test_picture_decisions import flag_by_the_detector, store_of

    store = store_of(launch_workspace)
    flag_by_the_detector(store, _HELD)
    ticked = next(p.asset_id for p in LIBRARY if p not in CARRIERS and p.asset_id != _HELD)
    d = screenshot_dir
    try:
        _open(page, f"{launch_app_url}/app/create", theme)
        cut_june(page, launch_app_url)
        page.get_by_role("link", name="Pool", exact=True).click()
        tiles = page.get_by_role("list", name="Pool").get_by_role("listitem")
        expect(tiles.first).to_be_visible(timeout=30_000)
        _save(page, d, _name("memory-pool-outcomes", theme))

        order = [picture.asset_id for picture in LIBRARY]
        held = tiles.nth(order.index(_HELD))
        expect(held.get_by_text(re.compile("^Held: "))).to_be_visible()
        _save_part(page, held, d, _name("pictures-pool-held", theme))
        held.get_by_role("button", name="Clear hold").click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        page.wait_for_timeout(400)
        _save_part(page, dialog, d, _name("pictures-clear-dialog", theme))
        dialog.get_by_role("button", name="Clear hold").click()
        expect(held.get_by_text(re.compile("^You cleared its hold"))).to_be_visible()
        _save_part(page, held, d, _name("pictures-pool-cleared", theme))

        other = tiles.nth(order.index(ticked))
        other.get_by_role("button", name="Never use").click()
        expect(other.get_by_text("You'll never use this picture.")).to_be_visible()
        _save_part(page, other, d, _name("pictures-pool-never-use", theme))
    finally:
        for asset_id in (_HELD, ticked):
            owner_decisions.forget(store, asset_id)


@pytest.mark.parametrize("theme", _THEMES)
def test_capture_the_pages_around_the_film(
    page: Page, launch_app_url: str, screenshot_dir: Path, theme: str
) -> None:
    """Runs, one run's details, suggestions, settings and people, as a first visit sees them."""
    d = screenshot_dir
    _open(page, f"{launch_app_url}/app/runs", theme)
    cards = page.get_by_role("list", name="Runs").get_by_role("listitem")
    expect(cards.first).to_be_visible(timeout=30_000)
    _save(page, d, _name("runs", theme))
    cards.first.get_by_role("link").first.click()
    page.wait_for_url("**/app/runs/**")
    page.get_by_role("heading", name="Run details").scroll_into_view_if_needed()
    _save(page, d, _name("run-details", theme))

    page.goto(f"{launch_app_url}/app/suggestions")
    expect(page.get_by_role("heading", level=1)).to_be_visible()
    page.wait_for_load_state("networkidle")
    _save(page, d, _name("suggestions", theme))

    page.goto(f"{launch_app_url}/app/settings")
    expect(page.get_by_role("heading", name="Immich Connection")).to_be_visible()
    page.wait_for_load_state("networkidle")
    _save(page, d, _name("settings-config", theme))

    page.goto(f"{launch_app_url}/app/settings/people")
    page.wait_for_load_state("networkidle")
    _save(page, d, _name("settings-people", theme))


@pytest.mark.parametrize("theme", _THEMES)
def test_capture_the_sign_in_page(
    page: Page,
    tmp_path_factory,
    unused_tcp_port_factory,
    fake_immich_server,
    screenshot_dir: Path,
    theme: str,
) -> None:
    """The sign-in page a `basic` install opens on."""
    from tests.e2e.conftest import _build_launch_environment
    from tests.e2e.web_flow import served_ui

    root = tmp_path_factory.mktemp("sign-in")
    env = _build_launch_environment(root)
    env |= {
        "IMMICH_URL": fake_immich_server.base_url,
        "IMMICH_API_KEY": fake_immich_server.api_key,
        "IMMICH_MEMORIES_AUTH__ENABLED": "true",
        "IMMICH_MEMORIES_AUTH__PROVIDER": "basic",
        "IMMICH_MEMORIES_AUTH__USERNAME": "owner",
        "IMMICH_MEMORIES_AUTH__PASSWORD": "screenshot-only",  # noqa: S105 - a throwaway fixture
    }
    with served_ui(env, unused_tcp_port_factory(), root / "server.log") as url:
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{url}/app/login")
        set_theme(page, theme)
        expect(page.get_by_role("button", name="Sign in")).to_be_visible()
        _save(page, screenshot_dir, _name("login", theme))
