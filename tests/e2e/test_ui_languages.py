"""Real browser sessions keep their interface language separate from one another."""

import contextlib
import re

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.fake_library import MONTH, YEAR

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


def _month_command(page, launch_app_url: str, labels: dict[str, str]) -> str:
    page.goto(launch_app_url + "/app/create")
    page.get_by_text(labels["type"], exact=True).click()
    page.get_by_label(labels["year"], exact=True).fill(str(YEAR))
    page.get_by_label(labels["month"], exact=True).select_option(str(MONTH))
    command = page.get_by_label(labels["command"])
    expect(command).to_contain_text(f"--month={MONTH}")
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
        french_command = _month_command(
            page,
            launch_app_url,
            {"type": "Moments du mois", "year": "Année", "month": "Mois", "command": "Commande"},
        )
        english_command = _month_command(
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
        # The run page's filters and the runs list's statuses are built at run time; they are
        # French too, not the English the client keeps them under.
        expect(page.get_by_role("radio", name="Toutes les images", exact=True)).to_be_visible(
            timeout=60_000
        )
        page.goto(launch_app_url + "/app/runs")
        expect(page.get_by_role("radio", name="Échouée", exact=True)).to_be_visible()
        expect(page.get_by_role("radio", name="Interrompue", exact=True)).to_be_visible()


# Every heading the progress panel shows, as the page draws it: a MutationObserver sees a
# stage that lasts a frame, which a poll from here could miss.
_RECORD_HEADINGS = """() => {
    window.__headings = window.__headings || [];
    const read = () => {
        for (const heading of document.querySelectorAll('section[aria-live="polite"] p.font-medium')) {
            const text = heading.textContent.trim();
            if (text && window.__headings.at(-1) !== text) window.__headings.push(text);
        }
    };
    new MutationObserver(read).observe(document.body, {subtree: true, childList: true, characterData: true});
    read();
}"""


def _english_chunks() -> set[str]:
    """The longest fixed piece of each English heading template, long enough to be telling."""
    from immich_memories.progress_text import STAGE_TEXTS

    chunks = set()
    for template in STAGE_TEXTS.values():
        pieces = [piece.strip(" .:;") for piece in re.split(r"\{\w+\}", template)]
        longest = max(pieces, key=len)
        if len(longest) >= 8:
            chunks.add(longest)
    return chunks


def _evidence_of(locator, name: str) -> None:
    """A picture of `locator` under UX_EVIDENCE_DIR, when it is set; nothing otherwise."""
    import os
    from pathlib import Path

    target = os.environ.get("UX_EVIDENCE_DIR")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        # WHY suppress: a panel that rerenders mid-capture costs one picture, not the test.
        with contextlib.suppress(Exception):
            locator.screenshot(path=str(Path(target) / f"{name}.png"))


def _watch_headings(
    page, panel, until, shots: list[str], name: str, timeout: float, unkeyed: list[str]
) -> None:
    """Poll the heading until `until()` holds, keeping one panel picture per new heading.

    The running job's own record is read too: a heading the server sends without a key is
    one the page can only show as the server wrote it, which is a leak a word list misses.
    """
    import time

    deadline = time.monotonic() + timeout
    while not until():
        assert time.monotonic() < deadline, f"{name} did not finish: {shots}"
        job = page.request.get(page.url.split("/app/", 1)[0] + "/api/v1/jobs/active").json()
        if job and job["status"] == "running":
            progress = job["progress"]
            stages = [progress, *progress["history"]]
            unkeyed.extend(stage["label"] for stage in stages if not stage["key"])
        heading = panel.locator("section[aria-live='polite'] p.font-medium").first
        text = heading.text_content(timeout=1_000) if heading.count() else None
        if text and text.strip() and (not shots or shots[-1] != text.strip()):
            shots.append(text.strip())
            _evidence_of(panel, f"{name}-{len(shots):02d}")
        page.wait_for_timeout(150)


def test_a_french_cut_and_render_show_every_progress_heading_in_french(
    browser: Browser, launch_app_url: str
):
    """#1960: from the first stage of the cut to the checked film, no heading is English."""
    with browser.new_context(locale="fr-FR", viewport={"width": 1280, "height": 900}) as french:
        page = french.new_page()
        page.add_init_script(f"document.addEventListener('DOMContentLoaded', {_RECORD_HEADINGS})")
        page.goto(launch_app_url + "/app/create")
        page.get_by_text("Moments du mois", exact=True).click()
        page.get_by_label("Année", exact=True).fill(str(YEAR))
        page.get_by_label("Mois", exact=True).select_option(str(MONTH))
        page.get_by_text("Durée et images").click()
        page.get_by_label("Durée en minutes", exact=False).fill("2")
        page.get_by_role("button", name="Monter", exact=True).click()
        seen: list[str] = []
        unkeyed: list[str] = []
        _watch_headings(
            page,
            page.locator("body"),
            lambda: "/app/runs/" in page.url,
            seen,
            "fr-cut",
            timeout=240,
            unkeyed=unkeyed,
        )
        expect(page.get_by_role("list", name="Planche-contact du montage").first).to_be_visible(
            timeout=30_000
        )
        cut_headings = page.evaluate("window.__headings || []")

        render_panel = page.get_by_role("region", name="Rendu", exact=True)
        render_panel.get_by_label("Résolution").select_option("720p")
        render_panel.get_by_label("Aucune musique").check()
        render_panel.get_by_role("button", name="Rendu", exact=True).click()
        failed = render_panel.get_by_text("Le traitement n’a pas abouti.")
        film = render_panel.locator("video")
        _watch_headings(
            page,
            render_panel,
            lambda: film.is_visible() or failed.is_visible(),
            seen,
            "fr-render",
            timeout=600,
            unkeyed=unkeyed,
        )
        assert not failed.is_visible(), render_panel.inner_text()
        headings = [*cut_headings, *page.evaluate("window.__headings || []"), *seen]
        # The finished render lists the stages it went through, worded from their keys too.
        render_panel.get_by_text("Étapes précédentes").click()
        history = render_panel.locator("details ol li").all_inner_texts()
        _evidence_of(render_panel, "fr-render-history")

    english = _english_chunks()
    shown = [*headings, *history]
    leaked = sorted({h for h in shown if "stage." in h or any(c in h for c in english)})
    assert history and not leaked, (history, leaked)
    assert not unkeyed, sorted(set(unkeyed))
    # The run really passed through the stages it words, in French.
    assert any(h.startswith("Lecture des dates") for h in headings), headings
    assert any("Encodage" in h or "Préparation des clips" in h for h in headings), headings
