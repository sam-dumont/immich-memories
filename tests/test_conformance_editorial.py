"""Editorial conformance exercises production judgments and checks their consequences."""

import json

import httpx

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import run_case


def test_worthiness_probe_distinguishes_race_from_routine(monkeypatch):
    from immich_memories.conformance.editorial_cases import editorial_cases

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"worthy":{"H1":"Crossing the race finish line"}}'},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: replace only the provider HTTP response; two-order voting and its bank stay real.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = editorial_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "memory worthiness"))
    assert result.valid, result.quality
    assert result.calls >= 2


def test_period_probe_exercises_reading_grouping_and_weighing(monkeypatch):
    from immich_memories.conformance.editorial_cases import editorial_cases

    def reply(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "Read a personal photo library" in prompt:
            body = {
                "fragments": [
                    {"reading": "r1", "episode": "S0001"},
                    {"reading": "r2", "episode": "S0002"},
                ],
                "new_episodes": [
                    {
                        "id": "S0001",
                        "title": "Cycling race",
                        "account": "A cycling race.",
                        "role": "central",
                    },
                    {
                        "id": "S0002",
                        "title": "Quiet afternoon",
                        "account": "Cat asleep at home.",
                        "role": "incidental",
                    },
                ],
            }
        elif "Group the day episodes" in prompt:
            body = {
                "thesis": "A cycling race and a quiet afternoon.",
                "about": ["S0001"],
                "stories": [
                    {"title": "Cycling race", "episodes": ["S0001"], "purpose": "Race day"},
                    {"title": "Quiet afternoon", "episodes": ["S0002"], "purpose": "At home"},
                ],
                "uncertainties": [],
            }
        else:
            body = {
                "weights": {"K01": "major", "K02": "minor"},
                "about": ["K01"],
                "join": [],
                "retitle": {},
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    # WHY: provider HTTP only; all three editorial stages use their production contracts.
    monkeypatch.setattr(
        httpx.AsyncClient, "_transport_for_url", lambda *_: httpx.MockTransport(reply)
    )
    checks = editorial_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "period story"))
    assert result.valid, result.quality
    assert result.calls == 4


def test_central_story_probe_requires_supported_candidate_votes(monkeypatch):
    from immich_memories.conformance.editorial_cases import editorial_cases

    def reply(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        body = {"about": ["K01"]}
        if "central-story-confirmation-v1" not in prompt:
            body |= {
                "weights": {"K01": "major", "K02": "minor", "K03": "minor"},
                "join": [],
                "retitle": {},
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    # WHY: provider HTTP only; both context votes and weighting are real production decisions.
    monkeypatch.setattr(
        httpx.AsyncClient, "_transport_for_url", lambda *_: httpx.MockTransport(reply)
    )
    checks = editorial_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "central story confirmation"))
    assert result.valid, result.quality
    assert result.calls == 4


def test_moment_probe_selects_participation_over_an_empty_view(monkeypatch):
    from immich_memories.conformance.editorial_cases import editorial_cases

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"keep":["M01"]}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: provider HTTP only; the pick's validation and both order votes run normally.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = editorial_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "story moment selection"))
    assert result.valid, result.quality
    assert result.calls == 2


def test_recurring_activity_probe_folds_repeated_swimming_days(monkeypatch):
    from immich_memories.conformance.editorial_cases import editorial_cases

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"same":[["K01","K02"]]}'}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: only the provider HTTP reply is replaced; activity nomination and folding are real.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = editorial_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "recurring activity"))
    assert result.valid, result.quality
    assert result.calls == 1


def test_moment_probe_does_not_pass_when_invalid_answers_fall_back_to_the_first_picture(
    monkeypatch,
):
    from immich_memories.conformance.editorial_cases import editorial_cases

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"keep":["unknown"]}'}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: an invalid provider reply deliberately triggers the production rules fallback.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = editorial_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "story moment selection"))
    assert not result.valid
    assert "fallback" in result.quality
