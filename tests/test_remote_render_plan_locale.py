"""#1958: the render-worker plan must carry a resolved locale, never "auto".

The worker builds its titles straight from the `titles` dict in the plan; if
"auto" travelled across the wire unresolved, the worker has no host locale of
its own to resolve it against, and the same English-only bug would reappear
one process over.
"""

from __future__ import annotations

from unittest.mock import patch

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.processing.remote_render_plan import build_render_request
from tests.conftest import make_clip


def _params(tmp_path, **config_overrides) -> GenerationParams:
    config = Config.model_validate(config_overrides)
    return GenerationParams(
        clips=[make_clip("test-clip-001", duration=5.0)],
        output_path=tmp_path / "memory.mp4",
        config=config,
    )


def test_locale_auto_is_resolved_before_it_reaches_the_worker(tmp_path):
    params = _params(tmp_path)
    assert params.config.title_screens.locale == "auto"

    # WHY: detect_system_locale is the host-locale boundary; mocking it stands
    # in for a French host without touching the real OS locale.
    with patch("immich_memories.i18n.detect_system_locale", return_value="fr"):
        request = build_render_request(params)

    assert request["titles"]["locale"] == "fr"


def test_explicit_locale_reaches_the_worker_unresolved_by_the_host(tmp_path):
    params = _params(tmp_path, title_screens={"locale": "fr"})

    with patch("immich_memories.i18n.detect_system_locale") as detect:
        request = build_render_request(params)
        detect.assert_not_called()

    assert request["titles"]["locale"] == "fr"
