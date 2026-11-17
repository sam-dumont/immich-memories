"""The worker takes every look the app's `defaults.scale_mode` offers."""

from __future__ import annotations

import pytest
from immich_memories_render_worker.models import RenderOptions
from pydantic import ValidationError


@pytest.mark.parametrize("look", ["blur", "fit", "crop", "auto"])
def test_the_worker_takes_every_look_the_app_offers(look):
    assert RenderOptions(scale_mode=look).scale_mode == look


def test_the_worker_refuses_a_look_the_app_does_not_offer():
    with pytest.raises(ValidationError):
        RenderOptions(scale_mode="smart_crop")
