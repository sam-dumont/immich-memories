"""The image serves the web client it built (#1580).

The client is not committed: the image's Node stage builds it. A build that lost it would
still start, and every page would say the client is not built, so this asks for the page.
"""

from __future__ import annotations

import pytest

from tests.container.deployment import APP

pytestmark = [pytest.mark.container]


def test_the_image_serves_the_built_web_client(deployment, upgraded):
    page = deployment.curl("-sS", "-w", "\nHTTP %{http_code}", f"http://{APP}:8080/app/login")
    body, _, status = page.rpartition("\nHTTP ")

    assert status.strip() == "200", page[-2000:]
    assert "_app/immutable/" in body
    assert "make web-build" not in body  # the page a server without its client shows
