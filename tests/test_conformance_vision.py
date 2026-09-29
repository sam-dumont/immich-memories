"""Vision conformance sends generated pixels through the production caption service path."""

import json

import httpx

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


def test_motion_probe_requires_movement_across_frames(monkeypatch):
    from immich_memories.conformance.vision_cases import vision_cases

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"description":"A blue ball moves from left to right."}'
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
