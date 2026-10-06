"""Platform pages export self-contained private stacks from the actual browser."""

import pytest
import yaml
from playwright.sync_api import expect

from tests.test_setup_builder_browser import setup_site as setup_site

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("platform", ["synology", "unraid", "portainer", "truenas"])
def test_platform_download_contains_inline_connection_and_private_storage(
    page, setup_site, tmp_path, platform
):
    page.goto(setup_site.removesuffix("/setup") + f"/docs/run/platforms/{platform}")
    expect(page.get_by_label("Immich API key")).to_have_count(0)
    expect(page.get_by_label("Release version", exact=True)).to_have_count(0)
    with page.expect_download() as event:
        page.get_by_role("button", name="Download docker-compose.yml", exact=True).click()
    destination = tmp_path / "docker-compose.yml"
    event.value.save_as(destination)
    compose = yaml.safe_load(destination.read_text())
    app = compose["services"]["immich-memories"]
    assert app["environment"]["IMMICH_API_KEY"] == "replace-with-your-immich-api-key"
    assert len(app["environment"]["IMMICH_MEMORIES_SECRET_KEY"]) == 64
    assert app["ports"] == ["127.0.0.1:8080:8080"]
    assert "immich-memories-output:/app/output" in app["volumes"]
    assert "env_file" not in app
