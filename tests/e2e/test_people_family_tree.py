"""Settings > People: the family tree, drawn in the browser from the confirmed relationships.

The fixture household is drawn for real: couples side by side, children under their parents,
the sibling group whose parents aren't in the tree under a dashed knot, and the friends left
out and counted. A person opens their card; a dotted suggestion's tick records it; the SVG and
PNG are made in the browser, and nothing is asked of any server but the app's own.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, expect

from immich_memories.people.companion import load_document
from immich_memories.people.transfer import import_document
from tests.e2e.family_tree_household import household, person_id

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("roster_restored")]


def _person(page: Page, name: str):
    return page.get_by_test_id("tree-person").filter(has=page.locator("title", has_text=name))


def _centre(page: Page, name: str) -> tuple[float, float]:
    box = _person(page, name).locator("circle").first.bounding_box()
    assert box is not None, name
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _open_tree(page: Page, launch_app_url: str, launch_workspace):
    import_document(launch_workspace.store(), household(), replace=True)
    page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded", timeout=30_000)
    tree = page.get_by_role("region", name="Family tree")
    tree.get_by_role("button", name="Draw the family tree").click()
    expect(tree.get_by_test_id("tree-person")).to_have_count(9, timeout=30_000)
    return tree


@pytest.mark.feature("web.people-family-tree")
def test_the_household_is_drawn_as_a_tree_with_couples_children_and_a_sibling_group(
    page: Page, launch_app_url: str, launch_workspace, tmp_path: Path
) -> None:
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url))
    tree = _open_tree(page, launch_app_url, launch_workspace)

    expect(tree.get_by_test_id("tree-couple")).to_have_count(2)
    expect(tree.get_by_test_id("tree-left-out")).to_have_text(
        "2 people with no family link are left out."
    )
    expect(tree.locator("[data-testid='tree-knot'][data-dashed='true']")).to_have_count(1)
    expect(tree.locator("[data-testid='tree-child'][data-dashed='true']")).to_have_count(2)
    expect(tree.locator("[data-owner='true']")).to_have_count(1)
    expect(_person(page, "Robin")).to_have_attribute("data-owner", "true")
    expect(_person(page, "Mo").get_by_test_id("tree-no-birth-year")).to_have_count(1)
    # Every face the fake Immich has is drawn: the image is not hidden by a failed load.
    page.wait_for_function(
        "() => [...document.querySelectorAll('[data-testid=tree-person] image')]"
        ".every(i => i.style.visibility !== 'hidden')"
    )
    # Rows are generations; Kit sits under Robin and Charlie's knot, within a person of it.
    (_, pat_y), (robin_x, robin_y) = _centre(page, "Pat"), _centre(page, "Robin")
    (charlie_x, charlie_y), (kit_x, kit_y) = _centre(page, "Charlie"), _centre(page, "Kit")
    assert pat_y < robin_y == charlie_y < kit_y
    assert abs(kit_x - (robin_x + charlie_x) / 2) < abs(robin_x - charlie_x)
    tree.screenshot(path=str(tmp_path / "family-tree.png"))
    assert (tmp_path / "family-tree.png").stat().st_size > 10_000

    _person(page, "Charlie").click()
    card = page.locator(f"#person-{person_id('Charlie')}")
    expect(card).to_be_focused()
    expect(page.get_by_label("Find a name")).to_have_value("Charlie")

    origin = urlsplit(launch_app_url).netloc
    assert {urlsplit(url).netloc for url in asked if url.startswith("http")} == {origin}

    # On a phone the tree scrolls inside its own box; the page never scrolls sideways.
    page.set_viewport_size({"width": 390, "height": 844})
    expect(tree.get_by_test_id("tree-person").first).to_be_attached()
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 390
    box = tree.bounding_box()
    assert box is not None and box["x"] + box["width"] <= 390


@pytest.mark.feature("web.people-family-tree")
def test_a_dotted_suggestion_is_confirmed_from_the_tree(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    tree = _open_tree(page, launch_app_url, launch_workspace)
    expect(tree.get_by_test_id("tree-suggestion")).to_have_count(1)

    tree.get_by_role("button", name="Confirm that Charlie is parent of Remy").click()

    expect(tree.get_by_test_id("tree-suggestion")).to_have_count(0, timeout=15_000)
    charlie = next(
        p for p in load_document(launch_workspace.store())["people"] if p["name"] == "Charlie"
    )
    assert {"parent-of", person_id("Remy")} <= {
        value for link in charlie["confirmed"]["links"] for value in (link["kind"], link["with"])
    }


@pytest.mark.feature("web.people-family-tree")
def test_the_tree_is_saved_as_svg_and_png_made_in_the_browser(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    tree = _open_tree(page, launch_app_url, launch_workspace)
    page.wait_for_load_state("networkidle")
    asked: list[str] = []
    page.on("request", lambda request: asked.append(f"{request.method} {request.url}"))

    with page.expect_download() as svg_download:
        tree.get_by_role("button", name="Save as SVG").click()
    svg = Path(svg_download.value.path()).read_text()
    with page.expect_download() as png_download:
        tree.get_by_role("button", name="Save as PNG").click()
    png = Path(png_download.value.path()).read_bytes()

    assert svg_download.value.suggested_filename == "family-tree.svg"
    assert svg.startswith("<svg") and "Robin" in svg
    assert "data:image/jpeg;base64," in svg, "the faces travel inside the file"
    assert "oklch" not in svg, "colours any SVG reader can draw"
    assert "tree-confirm" not in svg and "tree-suggestion" not in svg, "only what was confirmed"
    assert png.startswith(b"\x89PNG") and len(png) > 10_000
    # Making the files asks only for the faces, from the app's own server; nothing is sent.
    origin = urlsplit(launch_app_url).netloc
    assert all(
        line.startswith("GET ") and urlsplit(line[4:]).netloc in {origin, ""} for line in asked
    ), asked
