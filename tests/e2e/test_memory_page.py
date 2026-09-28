"""Making a memory in the web client on the hermetic launch: the brief, the cut, and its review."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.fake_editorial import PREVIEW_STAGE
from tests.e2e.fake_library import CARRIERS, HOME, LIBRARY, STORIES, THESIS
from tests.e2e.web_flow import contact_sheet, cut_june

pytestmark = pytest.mark.e2e

# The heaviest story leads the Stories view: the weights are the editor's own order.
_WEIGHT_ORDER = ("dominant", "major", "minor", "glimpse")
_BY_WEIGHT = [
    story.title
    for story in sorted(STORIES, key=lambda story: _WEIGHT_ORDER.index(story.weight))
    if any(picture.story_key == story.key for picture in CARRIERS)
]

# The Boolean override, and the fixture pictures holding both named faces.
_CONDITION = '"Robin" AND "Kit"'
_CONDITION_ASSETS = {
    picture.asset_id for picture in LIBRARY if {"Robin", "Kit"} <= set(picture.people)
}
# The same two names read the plain way: any one of them is enough.
_EITHER_ASSETS = {picture.asset_id for picture in LIBRARY if {"Robin", "Kit"} & set(picture.people)}


@pytest.fixture(autouse=True)
def _no_page_errors(page: Page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert errors == []


def _attempts(launch_workspace) -> set[Path]:
    return set(launch_workspace.cache_dir.glob("editorial-runs/*/attempts/*"))


def _request_of_the_cut_after(launch_workspace, before: set[Path]) -> dict:
    """The request this cut wrote, not one an earlier cut is still writing into."""
    written = _attempts(launch_workspace) - before
    assert written, "the cut opened no attempt"
    newest = max(written, key=lambda path: path.stat().st_mtime)
    return json.loads((newest / "status.private.json").read_text())["request"]


def _brief_for_june(page: Page, launch_app_url: str) -> None:
    page.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.get_by_label("Month", exact=True).select_option("6")


def _brief_for_trips(page: Page, launch_app_url: str, year: int) -> None:
    page.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_text("Trip", exact=True).click()
    page.get_by_label("Year", exact=True).fill(str(year))


def _progress(page: Page):
    return page.get_by_role("region", name="Progress")


def test_the_brief_offers_every_memory_type_generate_takes(page: Page, launch_app_url: str) -> None:
    from immich_memories.cli import main

    generate = main.commands["generate"]
    choices = next(p for p in generate.params if p.name == "memory_type").type.choices
    page.goto(f"{launch_app_url}/app/create")
    kinds = page.locator("input[name='kind']")
    expect(kinds).to_have_count(len(choices) + 1)

    offered = kinds.evaluate_all("inputs => inputs.map(i => i.value)")

    # `custom` is a date range with no --memory-type at all.
    assert sorted(offered) == sorted([*choices, "custom"])


def test_the_trip_picker_finds_the_lake_week_and_cuts_it(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    # Another test may have left a swapped library's trips in the server's cache.
    shutil.rmtree(launch_workspace.cache_dir / "web-answers", ignore_errors=True)
    _brief_for_trips(page, launch_app_url, 2024)
    cut = page.get_by_role("button", name="Cut", exact=True)
    # Without a trip, generate only lists the year's trips: the form will not send that.
    expect(cut).to_be_disabled()
    trips = page.get_by_role("list", name="Trips").get_by_role("listitem")
    lake = trips.filter(has_text=re.compile(r"2024-06-21 – 2024-06-27.*7 days"))
    expect(lake).to_have_count(1, timeout=60_000)
    number = trips.all_inner_texts().index(lake.inner_text()) + 1
    lake.click()
    expect(page.get_by_label("Command")).to_contain_text(f"--trip-index={number}")

    cut.click()

    page.wait_for_url("**/app/runs/**", timeout=240_000)
    # The lake week's story, less the suitcase packed at home: a trip is cut from what was
    # taken away, as `generate --memory-type trip` cuts it.
    away = [p for p in CARRIERS if p.story_key == "S0002" and p.place != HOME]
    expect(contact_sheet(page)).to_have_count(len(away))


@pytest.mark.parametrize("middle_type", ["IMAGE", "VIDEO"])
def test_the_trip_picker_keeps_new_year_trips_whole_and_drops_buffer_only_trips(
    page: Page, launch_app_url: str, monkeypatch, middle_type: str, launch_workspace
) -> None:
    from tests.e2e import fake_immich

    dates = (
        "2023-12-05",
        "2023-12-07",
        "2023-12-30",
        "2023-12-31",
        "2024-01-01",
        "2025-01-05",
        "2025-01-07",
    )
    template = next(a for a in fake_immich.TIMELINE_ASSETS if a["exifInfo"]["city"] == "Annecy")
    home_video = next(
        a
        for a in fake_immich.TIMELINE_ASSETS
        if a["type"] == "VIDEO" and a["exifInfo"]["city"] == "Brussels"
    )
    assets = tuple(
        {
            **template,
            "id": f"new-year-{i}",
            "type": middle_type if i == 3 else "IMAGE",
            "fileCreatedAt": f"{day}T12:00:00.000Z",
        }
        for i, day in enumerate(dates)
    )
    # WHY: replace the HTTP fixture's library, keeping the real client and GPS detector.
    monkeypatch.setattr(fake_immich, "TIMELINE_ASSETS", (*assets, home_video))
    # The server keeps each year's trips; this library is new, so its answer must be too.
    shutil.rmtree(launch_workspace.cache_dir / "web-answers", ignore_errors=True)

    _brief_for_trips(page, launch_app_url, 2024)

    trips = page.get_by_role("list", name="Trips").get_by_role("listitem")
    expect(trips).to_have_count(1, timeout=60_000)
    expect(trips).to_contain_text(re.compile(r"2023-12-30 – 2024-01-01.*3 days · 3 pictures"))


@pytest.mark.parametrize("only_photos", [False, True])
def test_the_trip_picker_offers_a_year_with_only_photos(
    page: Page, launch_app_url: str, monkeypatch, only_photos: bool, launch_workspace
) -> None:
    from tests.e2e import fake_immich

    template = next(a for a in fake_immich.TIMELINE_ASSETS if a["exifInfo"]["city"] == "Annecy")
    photos = tuple(
        {
            **template,
            "id": f"photo-year-{day}",
            "type": "IMAGE",
            "fileCreatedAt": f"2018-07-0{day}T12:00:00.000Z",
        }
        for day in (1, 2, 3)
    )
    # WHY: cover both a photo-only year in a mixed library and a photo-only library.
    existing = () if only_photos else fake_immich.TIMELINE_ASSETS
    monkeypatch.setattr(fake_immich, "TIMELINE_ASSETS", (*existing, *photos))
    # The server keeps each year's trips; this library is new, so its answer must be too.
    shutil.rmtree(launch_workspace.cache_dir / "web-answers", ignore_errors=True)

    _brief_for_trips(page, launch_app_url, 2018)

    expect(page.get_by_role("list", name="Trips")).to_contain_text(
        re.compile(r"2018-07-01 – 2018-07-03.*3 days · 3 pictures"), timeout=60_000
    )


def test_a_first_cut_before_models_fetch_says_to_run_it_and_the_message_stays(
    page: Page, first_launch_app_url: str, first_launch_workspace
) -> None:
    _brief_for_june(page, first_launch_app_url)
    log_before_cut = first_launch_workspace.log_path.stat().st_size

    page.get_by_role("button", name="Cut", exact=True).click()

    refusal = _progress(page).get_by_text(re.compile(r"immich-memories models fetch"))
    expect(refusal.first).to_be_visible(timeout=60_000)
    expect(_progress(page).get_by_text("It did not finish.")).to_be_visible()
    # Refused before the pool loads: not one picture was asked of Immich.
    with first_launch_workspace.log_path.open() as log:
        log.seek(log_before_cut)
        after_cut = log.read()
    assert "/thumbnail" not in after_cut
    assert "/api/search/" not in after_cut
    # The command is what the reader has to copy into a terminal, so the message waits for them.
    page.reload()
    expect(refusal.first).to_be_visible(timeout=30_000)


def test_the_cut_opens_as_a_contact_sheet_in_the_order_the_film_plays(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    before = _attempts(launch_workspace)
    cut_june(page, launch_app_url, minutes=None)

    expect(page.get_by_text(THESIS)).to_be_visible()
    shots = contact_sheet(page)
    expect(shots).to_have_count(len(CARRIERS))
    played = shots.locator("img").evaluate_all(
        "images => images.map(image => decodeURIComponent(image.src.split('/assets/')[1].split('/')[0]))"
    )
    assert played == [picture.asset_id for picture in CARRIERS]
    expect(shots.first).to_contain_text(CARRIERS[0].taken_at[:10])
    expect(shots.last).to_contain_text(CARRIERS[-1].taken_at[:10])
    # The attempt keeps what each story was read from, so a later drift can be diffed.
    newest = max(_attempts(launch_workspace) - before, key=lambda path: path.stat().st_mtime)
    provenance = json.loads((newest / "evidence-hashes.json").read_text())
    assert "IMG_" not in json.dumps(provenance)
    # What generate named the cut from is kept for a render made later (`runs render`):
    # its own title, or the preset the template title is built from (a None title).
    titles = json.loads((newest / "cut-titles.private.json").read_text())
    assert titles["title"] or titles["preset_params"]


def test_the_stories_view_weighs_the_stories_in_reader_words(
    page: Page, launch_app_url: str
) -> None:
    cut_june(page, launch_app_url, minutes=None)

    page.get_by_role("radio", name="Stories").click()

    stories = page.get_by_role("list", name="Stories")
    expect(stories.get_by_role("heading", level=3)).to_have_text(_BY_WEIGHT)
    for badge in ("Main story", "Important", "Small moment"):
        expect(stories.get_by_text(badge, exact=True).first).to_be_visible()
    for machine_word in ("dominant", "major", "glimpse"):
        expect(stories.get_by_text(machine_word, exact=True)).to_have_count(0)
    # Every carrier is reachable from its story, and opens in the inspector.
    carriers = stories.get_by_role("button")
    expect(carriers).to_have_count(len(CARRIERS))
    carriers.first.click()
    expect(page.get_by_role("article", name="Picture review")).to_be_visible()
    page.get_by_role("radio", name="Contact sheet").click()
    expect(contact_sheet(page)).to_have_count(len(CARRIERS))


def test_the_inspector_keeps_a_refused_model_alternative_distinct_from_the_cut(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    before = _attempts(launch_workspace)
    cut_june(page, launch_app_url, minutes=None)
    attempt = max(_attempts(launch_workspace) - before, key=lambda path: path.stat().st_mtime)
    original = next(picture for picture in CARRIERS if picture.is_favorite)
    alternative, replaced = [picture for picture in LIBRARY if picture not in CARRIERS][:2]
    newcomer = next(picture for picture in CARRIERS if picture is not original)
    folder = attempt / "derived-decisions"
    folder.mkdir(exist_ok=True)
    # WHY: the fixture replaces inference; the browser still reads the saved production format.
    (folder / "thin-polish.private.json").write_text(
        json.dumps(
            {
                "ran": True,
                "verdicts": {
                    original.asset_id: {
                        "state": "kept",
                        "named_by": 2,
                        "why": "Repeated viewpoint",
                        "protected": True,
                        "held_by": "the owner starred it or the catalogue records it",
                        "rule": "thesis-fit vote",
                    }
                },
                "slots": [
                    {
                        "replacing": original.asset_id,
                        "chosen": alternative.asset_id,
                        "offered": "2",
                        "outcome": "refused by look-alike",
                    },
                    {
                        "rule": "vote-weak",
                        "replacing": replaced.asset_id,
                        "chosen": newcomer.asset_id,
                        "offered": "3",
                        "outcome": "seated",
                    },
                ],
                "revoked_by_the_fit_check": [],
            }
        )
    )
    page.reload(wait_until="domcontentloaded")
    contact_sheet(page).nth(CARRIERS.index(original)).click()
    inspector = page.get_by_role("article", name="Picture review")
    expect(inspector.get_by_text("Repeated viewpoint")).to_be_visible()
    expect(
        inspector.get_by_text("the owner starred it or the catalogue records it")
    ).to_be_visible()
    expect(inspector.get_by_text("refused by look-alike", exact=True)).to_be_visible()
    expect(inspector.get_by_role("img", name="Recorded alternative")).to_have_attribute(
        "src", re.compile(re.escape(alternative.asset_id))
    )
    expect(inspector.get_by_role("button", name="Remove from this cut")).to_be_visible()

    contact_sheet(page).nth(CARRIERS.index(newcomer)).click()
    expect(inspector.get_by_text("Replaced a picture the model doubted.")).to_be_visible()
    expect(inspector.get_by_role("img", name="The picture it replaced")).to_have_attribute(
        "src", re.compile(re.escape(replaced.asset_id))
    )


def test_a_reload_mid_cut_joins_the_running_cut_instead_of_starting_another(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    before = _attempts(launch_workspace)
    _brief_for_june(page, launch_app_url)
    page.get_by_role("button", name="Cut", exact=True).click()
    expect(_progress(page).get_by_role("progressbar")).to_be_visible(timeout=30_000)

    page.reload(wait_until="domcontentloaded", timeout=30_000)

    expect(_progress(page)).to_be_visible(timeout=30_000)
    page.wait_for_url("**/app/runs/**", timeout=240_000)
    expect(page.get_by_text(THESIS)).to_be_visible()
    assert len(_attempts(launch_workspace) - before) == 1


def test_the_cut_shows_the_pictures_it_is_working_on_while_it_works(
    page: Page, launch_app_url: str
) -> None:
    """The wait has to look alive: the user's own library goes past, and a bar moves."""
    _brief_for_june(page, launch_app_url)
    page.get_by_role("button", name="Cut", exact=True).click()

    strip = _progress(page).get_by_role("list", name="Pictures just read").locator("img")
    expect(strip.first).to_be_visible(timeout=60_000)
    assert strip.count() <= 8
    # A real count for the pass that reports numbers, from the engine's own record.
    expect(_progress(page).get_by_text(re.compile(rf"\d+ of {len(LIBRARY)}"))).to_be_visible(
        timeout=60_000
    )
    expect(_progress(page).get_by_role("progressbar")).to_have_count(1)
    expect(_progress(page).get_by_text(PREVIEW_STAGE, exact=False).first).to_be_visible()
    page.wait_for_url("**/app/runs/**", timeout=240_000)
    expect(contact_sheet(page)).to_have_count(len(CARRIERS))


def test_cancel_ends_the_cut_and_offers_to_cut_again(page: Page, launch_app_url: str) -> None:
    _brief_for_june(page, launch_app_url)
    page.get_by_role("button", name="Cut", exact=True).click()
    expect(_progress(page)).to_be_visible(timeout=30_000)

    _progress(page).get_by_role("button", name="Cancel").click()

    expect(_progress(page).get_by_text("Stopped.")).to_be_visible(timeout=60_000)
    expect(page.get_by_role("button", name="Cut", exact=True)).to_be_enabled()


def test_the_pool_loads_its_pictures_through_the_thumbnail_route(
    page: Page, launch_app_url: str
) -> None:
    """No base64 data URI in the DOM: every thumbnail is an <img> the browser fetches and caches."""
    cut_june(page, launch_app_url, minutes=None)
    page.get_by_role("link", name="Pool", exact=True).click()
    tiles = page.get_by_role("list", name="Pool").get_by_role("listitem")
    expect(tiles.first).to_be_visible(timeout=30_000)
    # A page at a time, loaded as the last one scrolls into view: the DOM grows with reading.
    while tiles.count() < len(LIBRARY):
        seen = tiles.count()
        tiles.last.scroll_into_view_if_needed()
        expect(tiles).not_to_have_count(seen, timeout=10_000)
    expect(tiles).to_have_count(len(LIBRARY))

    routed = page.locator("img[src*='/api/v1/assets/']")
    assert page.locator("img[src^='data:']").count() == 0
    assert routed.count() >= len(LIBRARY)
    page.wait_for_function(
        "image => image.complete && image.naturalWidth > 0", arg=routed.first.element_handle()
    )


def test_the_people_condition_reaches_the_cut(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    """Quoted names are the override, folded away, and they still narrow a cut (#887)."""
    _brief_for_june(page, launch_app_url)
    condition = page.get_by_label("People condition")
    expect(condition).to_be_hidden()

    page.get_by_text("Grouped condition", exact=True).click()
    condition.fill(_CONDITION)
    expect(page.get_by_label("Command")).to_contain_text("--people-expression")
    expect(page.get_by_label("Command")).not_to_contain_text("--person=")

    before = _attempts(launch_workspace)
    page.get_by_role("button", name="Cut", exact=True).click()
    page.wait_for_url("**/app/runs/**", timeout=240_000)

    request = _request_of_the_cut_after(launch_workspace, before)
    assert set(request["requested_assets"]) == _CONDITION_ASSETS


def test_two_names_ask_together_or_any_of_them(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    """Two names and one word for what they mean is the whole plain path (#887)."""
    _brief_for_june(page, launch_app_url)
    match = page.get_by_label("Pictures with")
    expect(match).to_be_hidden()

    people = page.get_by_role("group", name="Only with (optional)")
    people.get_by_text("Robin", exact=True).click()
    # One name means nothing to choose between; the second is what raises the question.
    expect(match).to_be_hidden()
    people.get_by_text("Kit", exact=True).click()
    match.select_option("or")
    expect(page.get_by_label("Command")).to_contain_text("--person-match=or")

    before = _attempts(launch_workspace)
    page.get_by_role("button", name="Cut", exact=True).click()
    page.wait_for_url("**/app/runs/**", timeout=240_000)

    requested = set(_request_of_the_cut_after(launch_workspace, before)["requested_assets"])
    assert requested == _EITHER_ASSETS
    assert requested > _CONDITION_ASSETS


def test_an_album_is_cut_from_its_own_pictures_only(page: Page, launch_app_url: str) -> None:
    from tests.e2e.fake_immich import ALBUM_ASSETS, ALBUM_ID

    page.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_text("Album", exact=True).click()
    album = page.get_by_role("combobox", name="Album")
    expect(album.locator("option", has_text="The lake week")).to_have_count(1, timeout=30_000)
    album.select_option(ALBUM_ID)
    # The id, not the name: two albums may share one, and --from-album takes either.
    expect(page.get_by_label("Command")).to_contain_text(f"--from-album={ALBUM_ID}")

    page.get_by_role("button", name="Cut", exact=True).click()

    page.wait_for_url("**/app/runs/**", timeout=240_000)
    shots = contact_sheet(page)
    expect(shots.first).to_be_visible(timeout=30_000)
    played = shots.locator("img").evaluate_all(
        "images => images.map(i => decodeURIComponent(i.src.split('/assets/')[1].split('/')[0]))"
    )
    assert played and set(played) <= ALBUM_ASSETS
