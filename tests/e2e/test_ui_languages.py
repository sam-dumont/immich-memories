"""Real browser sessions keep their interface language separate from one another."""

import pytest
from playwright.sync_api import Browser, expect

pytestmark = pytest.mark.e2e


def test_browser_language_and_saved_choice_are_session_local(browser: Browser, launch_app_url: str):
    with (
        browser.new_context(locale="fr-FR") as french,
        browser.new_context(locale="en-US") as english,
    ):
        page = french.new_page()
        page.goto(launch_app_url + "/settings/config")
        page.wait_for_url("**/app/settings")
        expect(page.locator("html")).to_have_attribute("lang", "fr")
        expect(page.get_by_role("link", name="Souvenir", exact=True).first).to_be_visible()
        other = english.new_page()
        other.goto(launch_app_url + "/app/settings")
        expect(other.get_by_role("link", name="Memory", exact=True).first).to_be_visible()

        page.get_by_role("combobox", name="Langue de l’interface").select_option(label="Deutsch")
        expect(page.get_by_role("link", name="Erinnerung", exact=True).first).to_be_visible()
        expect(page.locator("html")).to_have_attribute("lang", "de")
        page.reload()
        expect(page.get_by_role("link", name="Erinnerung", exact=True).first).to_be_visible()
        other.reload()
        expect(other.get_by_role("link", name="Memory", exact=True).first).to_be_visible()
        expect(other.locator("html")).to_have_attribute("lang", "en")


def _june_command(page, launch_app_url: str, labels: dict[str, str]) -> str:
    page.goto(launch_app_url + "/app/create")
    page.get_by_text(labels["type"], exact=True).click()
    page.get_by_label(labels["year"], exact=True).fill("2024")
    page.get_by_label(labels["month"], exact=True).select_option("6")
    command = page.get_by_label(labels["command"])
    expect(command).to_contain_text("--month=6")
    return command.inner_text()


def test_french_choices_make_a_cut_without_changing_the_film_language(
    browser: Browser, launch_app_url: str
):
    """The interface language stays in the browser: the cut runs the command an English page runs."""
    with (
        browser.new_context(locale="fr-FR") as french,
        browser.new_context(locale="en-US") as english,
    ):
        page = french.new_page()
        french_command = _june_command(
            page,
            launch_app_url,
            {"type": "Moments du mois", "year": "Année", "month": "Mois", "command": "Commande"},
        )
        english_command = _june_command(
            english.new_page(),
            launch_app_url,
            {"type": "Monthly Highlights", "year": "Year", "month": "Month", "command": "Command"},
        )
        assert french_command == english_command
        assert "locale" not in french_command and "language" not in french_command

        page.get_by_role("button", name="Monter", exact=True).click()
        page.wait_for_url("**/app/runs/**", timeout=240_000)
        expect(page.locator("html")).to_have_attribute("lang", "fr")
        expect(page.get_by_role("link", name="Retour aux exécutions")).to_be_visible(timeout=30_000)
