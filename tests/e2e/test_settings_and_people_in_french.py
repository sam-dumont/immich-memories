"""Settings and a People relationship read in French: no raw key, no server English (#1965)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser, expect

from immich_memories.people.transfer import import_document
from tests.e2e.test_people_owner_and_links import _entry, _related

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("roster_restored")]

RAW_KEY = re.compile(r"^[a-z_]+(\.[a-z_]+)+$")


@pytest.mark.feature("web.settings")
def test_settings_sections_and_fields_are_worded_in_french(browser: Browser, launch_app_url: str):
    with browser.new_context(locale="fr-FR") as french:
        page = french.new_page()
        page.goto(f"{launch_app_url}/app/settings", wait_until="domcontentloaded")
        section = page.locator("details").filter(has_text="Modèle de langage").first
        expect(section).to_be_visible(timeout=30_000)
        section.locator("summary").click()

        expect(section.get_by_label("Modèle", exact=True)).to_be_visible()
        expect(section.get_by_label("Délai d'attente (secondes)")).to_be_visible()
        text = section.inner_text()
        assert "Language model" not in text and "Timeout" not in text
        names = page.eval_on_selector_all(
            "details [aria-label]", "els => els.map(e => e.getAttribute('aria-label'))"
        )
        assert names, "no settings controls rendered"
        assert [name for name in names if RAW_KEY.match(name)] == []
        headings = page.locator("details > summary").all_inner_texts()
        assert "Film defaults" not in headings and "Réglages par défaut des films" in headings


@pytest.mark.feature("web.people")
def test_a_relationship_reads_in_french_with_its_dropdown_and_confirm_text(
    browser: Browser, launch_app_url: str, launch_workspace
):
    ana, luc = _entry(0, "Ana Example"), _entry(1, "Luc Sample")
    _related(ana, "parent-of", 1, "child-of")
    _related(luc, "child-of", 0, "parent-of")
    import_document(launch_workspace.store(), {"version": 1, "people": [ana, luc]}, replace=True)

    with browser.new_context(locale="fr-FR") as french:
        page = french.new_page()
        page.goto(f"{launch_app_url}/settings/people", wait_until="domcontentloaded")
        card = page.get_by_role("listitem").filter(
            has=page.locator("p.font-semibold", has_text="Ana Example")
        )
        row = card.get_by_test_id("relationship-row")
        expect(row).to_contain_text("Ana Example est le parent de Luc Sample", timeout=30_000)
        assert " of " not in row.inner_text() and "is " not in row.inner_text()
        expect(card.get_by_label("Relationship", exact=True)).to_have_count(0)
        options = card.get_by_label("Lien", exact=True).locator("option").all_inner_texts()
        assert "parent de" in options and "parent of" not in options
