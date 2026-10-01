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

import base64
import re
import subprocess
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urljoin

import pytest
import yaml
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tests.e2e.conftest import _launch_workspace, _serve_launch, set_theme
from tests.e2e.fake_library import CARRIERS, LIBRARY, THESIS
from tests.e2e.redaction import redact_page
from tests.e2e.web_flow import contact_sheet, cut_june, render, the_film

pytestmark = [pytest.mark.e2e, pytest.mark.visual]

_THEMES = ("light", "dark")
# Tall enough for the whole brief down to Cut, and the render panel down to Render.
_VIEWPORT = {"width": 1440, "height": 1000}


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
    # WHY: Linux Chromium hints glyphs to the pixel grid, which spreads Inter's letters; the docs
    # show the client the way a desktop browser draws it, whatever machine captured it.
    args = [*browser_type_launch_args.get("args", []), "--font-render-hinting=none"]
    return {**browser_type_launch_args, "args": args}


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
        " return r.height > 0 && r.bottom > 0 && r.top < innerHeight"
        " && getComputedStyle(i).visibility !== 'hidden'; }).every(i => i.complete)",
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


def _save_padded(page: Page, locator, directory: Path, name: str, pad: int = 24) -> None:
    """A part of the page with room around it, so its borders are not cut at the frame's edge."""
    _to_top(locator, 96)
    _settle(page)
    box = locator.bounding_box()
    assert box is not None
    page.screenshot(
        path=str(directory / f"{name}.png"),
        clip={
            "x": box["x"] - pad,
            "y": box["y"] - pad,
            "width": box["width"] + 2 * pad,
            "height": box["height"] + 2 * pad,
        },
    )


def _to_top(locator, margin: int = 24) -> None:
    """Scroll `locator` to the top of whatever scrolls it: the app scrolls its main column,
    not the window, so `window.scrollTo` moves nothing."""
    locator.evaluate(
        "(el, m) => { el.style.scrollMarginTop = m + 'px'; el.scrollIntoView({block: 'start'}); }",
        margin,
    )


def _blur(page: Page) -> None:
    page.evaluate("document.activeElement && document.activeElement.blur()")


# The job panel follows the cut through server-sent events, and every event swaps the row of
# pictures just read, so during a counted stage that row is always half loaded. `__holdJobs`
# lets the capture hold the panel still for a moment; EventSource reconnects on release and the
# server sends the job as it is by then, so nothing the page needs is lost.
_HOLDABLE_JOBS = """
window.__holdJobs = false;
const Base = window.EventSource;
window.EventSource = class extends Base {
  set onmessage(handler) {
    super.onmessage = (event) => { if (!window.__holdJobs) handler(event); };
  }
  get onmessage() { return super.onmessage; }
};
"""


def _hold_a_counted_stage(page: Page) -> None:
    """Hold the job panel on a counted stage whose row of pictures has fully loaded."""
    counted = (
        "() => { const panel = document.querySelector('[aria-label=\"Progress\"]');"
        " const imgs = document.querySelectorAll('[aria-label=\"Pictures just read\"] img');"
        " return panel && /\\d+ of \\d+/.test(panel.textContent) && imgs.length >= 6; }"
    )
    loaded = (
        "() => [...document.querySelectorAll('[aria-label=\"Pictures just read\"] img')]"
        ".every(i => i.complete)"
    )
    for _ in range(20):
        page.wait_for_function(counted, polling=50, timeout=120_000)
        page.evaluate("window.__holdJobs = true")
        try:
            page.wait_for_function(loaded, timeout=5_000)
        except PlaywrightTimeoutError:
            page.evaluate("window.__holdJobs = false")
            continue
        return
    raise AssertionError("no counted stage held still long enough to load its pictures")


def _open(page: Page, url: str, theme: str) -> None:
    page.add_init_script(_HOLDABLE_JOBS)
    page.set_viewport_size(_VIEWPORT)
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    set_theme(page, theme)


def _brief_for_june(page: Page) -> None:
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.get_by_label("Month", exact=True).select_option("6")


@pytest.mark.parametrize("theme", _THEMES)
def test_capture_memory_walkthrough(
    page: Page, launch_app_url: str, screenshot_dir: Path, theme: str
) -> None:
    """The brief, the cut, the review, an edit, the render: every frame the docs embed."""
    d = screenshot_dir
    _open(page, f"{launch_app_url}/app/create", theme)
    _brief_for_june(page)
    # The brief as a first visit sees it: the type, the month, the command and Cut, no panel open.
    _blur(page)
    _save(page, d, _name("memory-brief", theme))
    _save_padded(
        page, page.get_by_role("main").locator("form").first, d, _name("first-film-brief", theme)
    )
    page.get_by_text("Length and pictures").click()
    # The fixture month holds 79 s of pictures and video; 1.5 minutes leaves room for the titles
    # and stays inside the accepted shortfall, so the review shows no "selected less" notice.
    page.get_by_label("Length in minutes", exact=False).fill("1.5")
    page.get_by_label("Who may see it").select_option("just-us")
    _blur(page)
    _save(page, d, _name("memory-brief-sharing", theme))
    page.get_by_label("Who may see it").select_option("")

    page.get_by_role("button", name="Cut", exact=True).click()
    progress = page.get_by_role("region", name="Progress")
    expect(progress).to_be_visible(timeout=60_000)
    _hold_a_counted_stage(page)
    _save(page, d, _name("memory-cutting", theme))
    _save_padded(page, progress, d, _name("first-film-progress", theme))
    page.evaluate("window.__holdJobs = false")

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
    # Both edits sit in the first row: show that row, the inspector beside it and the change bar.
    _to_top(page.get_by_role("list", name="Cut contact sheet"), 64)
    _save(page, d, _name("memory-review-edit", theme))
    # Close the comparison so the focused capture ends after the replacement strip.
    inspector.get_by_role("list", name="Other pictures of this moment").locator(
        'button[aria-pressed="true"]'
    ).click()
    # Capture the editing controls with room around the complete replacement strip.
    # The full inspector is taller than the viewport and its sticky change bar obscures it.
    # Give the inspector enough vertical room that the sticky revision bar cannot cover it.
    capture_viewport = page.viewport_size
    assert capture_viewport is not None
    page.set_viewport_size({**capture_viewport, "height": 1600})
    _to_top(inspector, 64)
    # Add breathing room after this section, without altering its controls or content.
    alternatives_section = inspector.get_by_role(
        "list", name="Other pictures of this moment"
    ).locator("xpath=..")
    alternatives_section.evaluate("el => el.style.paddingBottom = '24px'")
    _settle(page)
    box = inspector.bounding_box()
    alternatives = alternatives_section.bounding_box()
    assert box is not None and alternatives is not None
    page.screenshot(
        path=str(d / f"{_name('first-film-edit', theme)}.png"),
        clip={
            "x": box["x"] - 24,
            "y": box["y"] - 24,
            "width": box["width"] + 48,
            "height": alternatives["y"] + alternatives["height"] - box["y"] + 24,
        },
    )
    alternatives_section.evaluate("el => el.style.paddingBottom = ''")
    page.set_viewport_size(capture_viewport)
    page.get_by_role("button", name="Save revision").click()
    expect(page.get_by_role("status").filter(has_text="Saved as revision")).to_be_visible()

    panel = page.get_by_role("region", name="Render")
    panel.get_by_label("What to render").select_option(label="Revision 1")
    _to_top(panel)
    _save(page, d, _name("memory-options", theme))
    render(page, resolution="720p")
    expect(the_film(page)).to_be_visible(timeout=600_000)
    _show_the_film_at(page, 19.5, d)
    _to_top(panel)
    _save(page, d, _name("memory-export", theme))


def _show_the_film_at(page: Page, seconds: float, scratch: Path) -> None:
    """Put a frame of the rendered film in the page's player, the birthday candles the demo
    shows too.

    WHY: Playwright's Chromium ships without an H.264 decoder, so the player reads the film's
    length and never draws a frame: a blank box, or a spinner. The frame comes from the very file
    the page is playing, cut out with FFmpeg and set as the player's poster.
    """
    film = the_film(page)
    source = film.evaluate("v => v.currentSrc || v.src")
    body = page.request.get(urljoin(page.url, source)).body()
    movie, still = scratch / ".film.mp4", scratch / ".film.jpg"
    movie.write_bytes(body)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(seconds),
                "-i",
                str(movie),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(still),
            ],
            check=True,
        )
        poster = "data:image/jpeg;base64," + base64.b64encode(still.read_bytes()).decode()
    finally:
        movie.unlink(missing_ok=True)
        still.unlink(missing_ok=True)
    # Without a decoder the controls read 0:00 and greyed out, which looks broken; the frame alone
    # reads as the film.
    film.evaluate("(v, url) => { v.pause(); v.poster = url; v.controls = false; }", poster)


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
    """The pool's outcomes, a held picture and its clear dialog, Never use (#1324), and the
    ticks previewed as a revision of the same cut."""
    from immich_memories.store import owner_decisions
    from tests.e2e.test_picture_decisions import flag_by_the_detector, store_of

    store = store_of(launch_workspace)
    flag_by_the_detector(store, _HELD)
    ticked = next(p.asset_id for p in LIBRARY if p not in CARRIERS and p.asset_id != _HELD)
    d = screenshot_dir
    try:
        _open(page, f"{launch_app_url}/app/create", theme)
        cut_june(page, launch_app_url, minutes=1.5)
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

        # The owner's last pass: tick the held picture in and preview it, nothing chosen again.
        held.get_by_role("checkbox", name="In the film").check()
        expect(page.get_by_text(re.compile(r"^Add: 1"))).to_be_visible()
        _save(page, d, _name("memory-pool-choices", theme))
        page.get_by_role("button", name="Preview with these choices").click()
        added = page.get_by_role("list", name="Added from the pool")
        expect(added.get_by_role("img")).to_have_count(1, timeout=30_000)
        added.scroll_into_view_if_needed()
        _save(page, d, _name("memory-pool-revision", theme))
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
    # Every pass adds runs, so the light and dark lists would differ; the last pass takes both.
    if theme == _THEMES[-1]:
        for shade in _THEMES:
            set_theme(page, shade)
            _save(page, d, _name("runs", shade))
        set_theme(page, theme)
    # The details worth showing belong to a film: its output path, delivery and phase timings.
    # The newest card can be a cut or a preview, so open cards until one was rendered.
    links = [
        cards.nth(i).get_by_role("link").first.get_attribute("href") for i in range(cards.count())
    ]
    details = page.get_by_role("heading", name="Run details")
    for href in links:
        page.goto(urljoin(launch_app_url, href or ""))
        expect(details).to_be_visible(timeout=30_000)
        if page.get_by_text(re.compile(r"^Saved to: ")).count():
            break
    _save_padded(page, details.locator("xpath=.."), d, _name("run-details", theme))

    page.goto(f"{launch_app_url}/app/suggestions")
    expect(page.get_by_role("heading", level=1)).to_be_visible()
    page.wait_for_load_state("networkidle")
    _save(page, d, _name("suggestions", theme))

    page.goto(f"{launch_app_url}/app/settings")
    expect(page.get_by_role("heading", name="Immich Connection")).to_be_visible()
    page.wait_for_load_state("networkidle")
    _save(page, d, _name("settings-config", theme))

    # The registry starts empty on a fresh host; the page is only worth a picture once it has
    # read who is in the library, which is what the first thing anyone does there is.
    page.goto(f"{launch_app_url}/app/settings/people")
    page.wait_for_load_state("networkidle")
    if page.get_by_text("Nobody yet.", exact=False).count():
        page.get_by_role("button", name="Rescan the library").click()
    roster = page.get_by_role("listitem").filter(has_text=re.compile(r"Pictures: \d+"))
    expect(roster.first).to_be_visible(timeout=120_000)
    # Opened again, as someone coming back to the page does: the roster, not the scan's panel.
    page.reload()
    expect(roster.first).to_be_visible(timeout=30_000)
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
        page.set_viewport_size(_VIEWPORT)
        page.goto(f"{url}/app/login")
        set_theme(page, theme)
        expect(page.get_by_role("button", name="Sign in")).to_be_visible()
        _save(page, screenshot_dir, _name("login", theme))


@pytest.fixture(scope="module")
def accounts_app_url(
    tmp_path_factory, fake_immich_server, unused_tcp_port_factory
) -> Generator[str, None, None]:
    """The hermetic launch with a second account, `partner`, which the fake service also answers."""
    workspace = _launch_workspace(tmp_path_factory.mktemp("accounts-shots"), fake_immich_server)
    config = yaml.safe_load(workspace.config_path.read_text())
    config["immich"]["accounts"] = {
        "partner": {"url": fake_immich_server.base_url, "api_key": fake_immich_server.api_key}
    }
    workspace.config_path.write_text(yaml.safe_dump(config))
    yield from _serve_launch(workspace, unused_tcp_port_factory(), models_fetched=True)


@pytest.mark.parametrize("theme", _THEMES)
def test_capture_a_second_account(
    page: Page, accounts_app_url: str, screenshot_dir: Path, theme: str
) -> None:
    """A person bound across two accounts, a saved group, and both on the New memory page."""
    d = screenshot_dir
    _open(page, f"{accounts_app_url}/app/settings/people", theme)
    page.wait_for_load_state("networkidle")
    if page.get_by_text("Nobody yet.", exact=False).count():
        page.get_by_role("button", name="Rescan the library").click()
    # Every card's relationship picker names Robin too; the card's own title is its first line.
    card = page.get_by_role("listitem").filter(
        has=page.locator("p.font-semibold", has_text="Robin")
    )
    expect(card).to_be_visible(timeout=120_000)
    bound = card.get_by_text("partner: partner-face-01")
    # The first theme's pass binds and saves; the second finds both already there.
    if not bound.count():
        card.get_by_label("Account", exact=True).select_option("partner")
        card.get_by_label("Their id in that account").fill("partner-face-01")
        card.get_by_role("button", name="Bind", exact=True).click()
    expect(bound).to_be_visible(timeout=15_000)
    groups = page.get_by_role("region", name="Saved groups")
    if not groups.get_by_text("Kids", exact=True).count():
        groups.get_by_label("Label", exact=True).fill("Kids")
        groups.get_by_label("Expression", exact=True).fill('"person-robin" OR "person-charlie"')
        groups.get_by_role("button", name="Save group", exact=True).click()
    expect(groups.get_by_text("Kids", exact=True)).to_be_visible(timeout=15_000)
    # Opened again, so the bind form is back to empty, as someone returning to the page sees it.
    page.reload()
    expect(bound).to_be_visible(timeout=30_000)
    page.wait_for_load_state("networkidle")
    # The cards sit 16 px apart; a narrower margin keeps the neighbours out of the frame.
    _save_padded(page, card, d, _name("people-accounts-bind", theme), pad=8)
    _save_padded(page, groups, d, _name("people-saved-groups", theme))

    page.goto(f"{accounts_app_url}/app/create", wait_until="domcontentloaded")
    page.get_by_text("Multi-Person", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    kids = page.get_by_role("button", name=re.compile(r"^Kids"))
    with page.expect_response(lambda r: r.url.endswith("/api/v1/cuts/command")):
        kids.click()
    for account in ("primary", "partner"):
        with page.expect_response(lambda r: r.url.endswith("/api/v1/cuts/command")):
            page.get_by_text(account, exact=True).click()
    command = page.locator("code[aria-label='Command']")
    expect(command).to_contain_text("--accounts=primary,partner")
    _blur(page)
    # From the people to the command they turn into, the two collapsed panels between them.
    people = page.get_by_role("group", name="People")
    _to_top(people, 96)
    _settle(page)
    top, bottom = people.bounding_box(), command.bounding_box()
    assert top is not None and bottom is not None
    page.screenshot(
        path=str(d / f"{_name('memory-brief-accounts', theme)}.png"),
        clip={
            "x": top["x"] - 24,
            "y": top["y"] - 24,
            "width": top["width"] + 48,
            # Only 6 px under the command: the Cut button starts 8 px below it.
            "height": bottom["y"] + bottom["height"] - top["y"] + 30,
        },
    )
