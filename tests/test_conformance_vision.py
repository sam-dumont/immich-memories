"""Vision conformance sends generated pixels through the production caption service path."""

import json

import httpx
import pytest

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import run_case


def test_caption_probe_requires_the_visible_red_rectangle(monkeypatch):
    from immich_memories.conformance.vision_cases import vision_cases

    def reply(request):
        content = json.loads(request.content)["messages"][0]["content"]
        assert any(part.get("type") == "image_url" for part in content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "description": "A red rectangle on a white background.",
                                    "setting": "graphic",
                                }
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    # WHY: only provider HTTP is substituted; PNG generation, controls and banking run normally.
    monkeypatch.setattr(
        httpx.AsyncClient, "_transport_for_url", lambda *_: httpx.MockTransport(reply)
    )
    checks = vision_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "image caption"))
    assert result.valid, result.quality
    assert result.calls == 4


@pytest.mark.parametrize("object_name", ["ball", "dot"])
def test_motion_probe_requires_movement_across_frames(monkeypatch, object_name):
    from immich_memories.conformance.vision_cases import vision_cases

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"description": f"A blue {object_name} moves from left to right."}
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: provider HTTP is the only boundary; the real motion seat builds its request.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = vision_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "video motion"))
    assert result.valid, result.quality
    assert result.calls == 1


@pytest.mark.parametrize(
    "reply",
    [
        '```json\n{"description":"A disc moves upward."}\n```',
        'Frames show {"description":"A disc moves upward."}',
    ],
)
def test_motion_keeps_complete_fenced_answers(reply):
    from immich_memories.analysis.editorial_preparation_motion import motion_text

    assert motion_text(reply) == "A disc moves upward."


def test_filmstrip_numbers_and_separates_frames_without_reordering_pixels():
    from io import BytesIO

    from PIL import Image, ImageDraw

    from immich_memories.analysis.editorial_preparation_motion import TILE, filmstrip

    frames = []
    for x in (40, 160, 280):
        image = Image.new("RGB", (400, 400), "white")
        ImageDraw.Draw(image).ellipse((x, 160, x + 70, 230), fill="blue")
        data = BytesIO()
        image.save(data, "PNG")
        frames.append(data.getvalue())
    with Image.open(BytesIO(filmstrip(frames))) as strip:
        assert strip.size == (TILE * 3, TILE + 24)
        for index, x in enumerate((40, 160, 280)):
            red, green, blue = strip.getpixel(
                (index * TILE + int((x + 35) * TILE / 400), 24 + int(195 * TILE / 400))
            )
            assert blue > 200 and red < 40 and green < 40
            assert max(strip.getpixel((index * TILE, TILE // 2))) < 60
        assert len(set(strip.crop((0, 0, TILE, 24)).get_flattened_data())) > 2


@pytest.mark.parametrize(
    "direction,description",
    [
        ("left", "A blue disc moves left."),
        ("up", "A blue disc moves upward."),
        ("down", "A blue disc moves downward."),
        ("stationary", "A blue disc stays stationary."),
    ],
)
def test_held_out_motion_controls_require_the_actual_direction(monkeypatch, direction, description):
    from immich_memories.conformance.vision_cases import motion

    # WHY: only the external model reply is replaced; frame generation and serialization run.
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"description": description})},
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    llm = LLMConfig(model="fixture", base_url="http://localhost:43210/v1")
    assert motion(llm, direction=direction)
    if direction != "stationary":
        with pytest.raises(AssertionError, match="movement"):
            motion(llm, direction="stationary")
