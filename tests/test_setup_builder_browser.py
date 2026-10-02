"""The real built setup form responds to choices without sending service requests."""

import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def setup_site(tmp_path_factory):
    if not (ROOT / "docs-site/build/setup/index.html").exists():
        pytest.skip("Run make docs-build before this browser check")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    log = tmp_path_factory.mktemp("setup-site") / "server.log"
    url = f"http://127.0.0.1:{port}/immich-video-memory-generator/setup"
    with log.open("w") as output:
        process = subprocess.Popen(
            ["make", "docs-serve", f"DOCS_PORT={port}"],
            cwd=ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310 — fixed loopback HTTP URL
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                pytest.fail(log.read_text())
            yield url
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)


def test_builder_changes_files_for_full_then_native_mac(page, setup_site):
    page.goto(setup_site)
    page.get_by_label("Immich API key", exact=True).fill("synthetic-fixture-api-key")
    expect(page.get_by_label("Release version", exact=True)).to_have_count(0)
    page.get_by_role("radio", name="Full").check()
    page.get_by_label("Reader URL", exact=True).fill("http://reader.example.lan:8000/v1")
    page.get_by_label("Reader model", exact=True).fill("served-model")
    page.get_by_text("Preview .env", exact=True).click()
    expect(page.locator("pre").filter(has_text="READER_ENABLED=true")).to_be_visible()
    expect(page.locator("pre").filter(has_text="docker compose up -d")).to_be_visible()

    page.get_by_label("Where will it run?", exact=True).select_option("mac")

    expect(page.locator("pre").filter(has_text="immich-memories[all-mac]")).to_be_visible()
    expect(
        page.locator("pre").filter(has_text="immich-memories ui --host 127.0.0.1")
    ).to_be_visible()
    expect(page.get_by_label("GPU box address (optional)", exact=True)).to_have_count(0)


def test_builder_mobile_has_no_horizontal_overflow_and_labels_are_usable(page, setup_site):
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(setup_site)
    page.get_by_label("Immich API key", exact=True).fill("synthetic-fixture-api-key")
    expect(page.get_by_label("Release version", exact=True)).to_have_count(0)
    page.get_by_text("Preview .env", exact=True).click()
    expect(page.locator("pre").filter(has_text="IMMICH_MEMORIES_VERSION=1.2.3")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_generated_file_download_preserves_the_actual_compose_content(page, setup_site, tmp_path):
    page.goto(setup_site)
    page.get_by_label("Immich API key", exact=True).fill("synthetic-fixture-api-key")
    expect(page.get_by_label("Release version", exact=True)).to_have_count(0)
    with page.expect_download() as event:
        page.get_by_role("button", name="Download docker-compose.yml", exact=True).click()
    download = event.value
    assert download.suggested_filename == "docker-compose.yml"
    destination = tmp_path / download.suggested_filename
    download.save_as(destination)
    assert '"immich-memories"' in destination.read_text()
    expect(page.locator("pre").filter(has_text="docker compose up -d")).to_be_visible()


def test_single_file_download_is_ready_for_a_stack_editor(page, setup_site, tmp_path):
    import json

    page.goto(setup_site)
    page.get_by_label("Immich API key", exact=True).fill("synthetic-fixture-api-key")
    expect(page.get_by_label("Release version", exact=True)).to_have_count(0)
    page.get_by_role("checkbox", name="Single file for a stack editor").check()
    expect(page.get_by_role("button", name="Download .env", exact=True)).to_have_count(0)
    with page.expect_download() as event:
        page.get_by_role("button", name="Download docker-compose.yml", exact=True).click()
    destination = tmp_path / "docker-compose.yml"
    event.value.save_as(destination)
    config = json.loads(destination.read_text())
    app = config["services"]["immich-memories"]
    assert app["image"].endswith(":1.2.3")
    assert "immich-memories-output:/app/output" in app["volumes"]
    assert "./output:/app/output" not in app["volumes"]
    assert len(app["environment"]["IMMICH_MEMORIES_SECRET_KEY"]) == 64
