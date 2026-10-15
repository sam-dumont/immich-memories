"""Config values (server addresses) never appear in the logs and errors a failure produces."""

from __future__ import annotations

import asyncio
import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from immich_memories.audio.generators.ace_step_backend import ACEStepBackend, ACEStepConfig

PRIVATE = "http://music.internal.example:9999"


def _failing_api(error: Exception | None = None, status: int | None = None) -> AsyncMock:
    client = AsyncMock()
    if error:
        client.get = AsyncMock(side_effect=error)
    else:
        response = MagicMock()
        response.status_code = status
        client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.parametrize(
    ("mode", "error", "status"),
    [
        ("lib", ConnectionError(f"refused {PRIVATE}"), None),
        ("api", ConnectionError(f"refused {PRIVATE}"), None),
        ("api", None, 503),
    ],
)
def test_ace_step_logs_never_name_the_configured_address(caplog, mode, error, status):
    backend = ACEStepBackend(ACEStepConfig(mode=mode, api_url=PRIVATE))

    # WHY: no real ACE-Step library or network in a unit test.
    with (
        patch(
            "immich_memories.audio.generators.ace_step_backend.is_ace_step_importable",
            return_value=False,
        ),
        # WHY: a checkout that ran `make install-acestep` has the isolated venv.
        patch(
            "immich_memories.audio.generators.ace_step_backend.ace_step_isolated.isolated_python",
            return_value=None,
        ),
        # WHY: the ACE-Step HTTP server is the network boundary.
        patch("httpx.AsyncClient", return_value=_failing_api(error, status)),
        caplog.at_level("WARNING"),
    ):
        assert asyncio.run(backend.is_available()) is False

    assert "internal.example" not in caplog.text
    assert caplog.text, "the failure is still logged"


def test_a_refused_caption_credential_does_not_name_the_endpoint():
    from immich_memories.analysis.captions.requests import _model_inventory

    refusal = urllib.error.HTTPError(PRIVATE, 401, "unauthorized", {}, None)  # type: ignore[arg-type]
    # WHY: the caption server is the network boundary.
    with (
        patch(
            "immich_memories.analysis.captions.requests.open_caption_url",
            side_effect=refusal,
        ),
        pytest.raises(PermissionError) as raised,
    ):
        _model_inventory(PRIVATE, timeout=1.0, api_key="")

    assert "internal.example" not in str(raised.value)
    assert "401" in str(raised.value)


def test_a_model_download_error_does_not_name_the_configured_url(tmp_path):
    from immich_memories.pinned_models import fetch_pinned_model

    with pytest.raises(ValueError) as raised:
        fetch_pinned_model(
            url="ftp://models.internal.example/x.onnx", destination=tmp_path / "x", sha256="0" * 64
        )

    assert "internal.example" not in str(raised.value)
