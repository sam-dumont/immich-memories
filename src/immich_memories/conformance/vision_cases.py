"""Generated geometric images, never library media, test caption and motion seats."""

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


def motion(llm: LLMConfig) -> str:
    frames = []
    for x in (40, 160, 280):
        image = Image.new("RGB", (400, 400), "white")
        ImageDraw.Draw(image).ellipse((x, 160, x + 70, 230), fill="blue")
        buffer = BytesIO()
        image.save(buffer, "PNG")
        frames.append(buffer.getvalue())
    ask = seat_asker(llm.base_url, api_key="", timeout=llm.timeout_seconds, llm_config=llm)
    text = motion_text(ask(filmstrip(frames))).lower()
    assert any(word in text for word in ("ball", "circle", "disc")), (
        "motion lost the visible object"
    )
    assert "right" in text and any(word in text for word in ("mov", "roll", "shift", "travel")), (
        "motion did not describe left-to-right movement"
    )
    return "describes the blue object's left-to-right movement"


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
