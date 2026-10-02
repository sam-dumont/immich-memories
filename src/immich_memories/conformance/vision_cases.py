"""Generated geometric images, never library media, test caption and motion seats."""

import re
from functools import partial
from io import BytesIO

from PIL import Image, ImageDraw

from immich_memories.analysis.editorial_preparation_captions import prepare_captions
from immich_memories.analysis.editorial_preparation_motion import filmstrip, motion_text, seat_asker
from immich_memories.analysis.llm_caption_identity import llm_caption_identity
from immich_memories.analysis.prepared_captions import prepared_captions
from immich_memories.config_loader import Config
from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.fixtures import scratch_store
from immich_memories.conformance.runtime import Case


def rectangle() -> bytes:
    image = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(image).rectangle((50, 125, 350, 275), fill="red")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def caption(llm: LLMConfig) -> str:
    with scratch_store() as (_, store):
        failures = prepare_captions(
            store=store,
            asset_ids=("rectangle",),
            preview_for=lambda _: rectangle(),
            base_url=llm.base_url,
            timeout=llm.timeout_seconds,
            concurrency=1,
            check_cancelled=lambda: None,
            progress=lambda *_: None,
            llm_config=llm,
        )
        assert not failures, "caption could not be produced"
        config = Config(llm=llm, editorial={"description_model": llm_caption_identity(llm)})
        text = prepared_captions(config, ("rectangle",)).get("rectangle", "").lower()
    assert "red" in text and any(word in text for word in ("rectangle", "rectangular")), (
        "caption did not describe the visible red rectangle"
    )
    return "caption identifies the generated red rectangle"


def motion(llm: LLMConfig, *, direction: str = "right") -> str:
    positions = {
        "right": [(40, 160), (160, 160), (280, 160)],
        "left": [(280, 160), (160, 160), (40, 160)],
        "up": [(160, 280), (160, 160), (160, 40)],
        "down": [(160, 40), (160, 160), (160, 280)],
        "stationary": [(160, 160)] * 3,
    }
    frames = []
    for x, y in positions[direction]:
        image = Image.new("RGB", (400, 400), "white")
        ImageDraw.Draw(image).ellipse((x, y, x + 70, y + 70), fill="blue")
        buffer = BytesIO()
        image.save(buffer, "PNG")
        frames.append(buffer.getvalue())
    ask = seat_asker(llm.base_url, api_key="", timeout=llm.timeout_seconds, llm_config=llm)
    text = motion_text(ask(filmstrip(frames))).lower()
    assert any(word in text for word in ("ball", "circle", "disc", "dot")), (
        "motion lost the visible object"
    )
    if direction == "stationary":
        assert any(
            word in text for word in ("stationary", "same position", "still", "does not move")
        ), "motion invented movement in stationary frames"
    else:
        orthogonal = ("left", "right") if direction in {"up", "down"} else ("up", "down")
        assert (
            not any(re.search(rf"\b{axis}(?:ward)?s?\b", text) for axis in orthogonal)
            and re.search(rf"\b{direction}(?:ward)?s?\b", text)
            and any(word in text for word in ("mov", "roll", "shift", "travel"))
            and "stationary" not in text
        ), f"motion did not describe {direction} movement"
    return f"describes the blue object's {direction} movement"


def vision_cases(llm: LLMConfig) -> tuple[Case, ...]:
    return (
        Case(
            "video motion",
            partial(motion, llm),
            frozenset({"analysis.editorial_preparation_motion:seat_asker.ask"}),
        ),
        Case(
            "image caption",
            partial(caption, llm),
            frozenset(
                {
                    "analysis.editorial_preparation_captions:_ask_llm",
                    "analysis.editorial_preparation_captions:ask_llm_image",
                }
            ),
        ),
    )
