"""Lexical conformance still uses a real WordNet reader and the production questions."""

import json

import httpx

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.lexical_cases import lexical_cases
from immich_memories.conformance.runtime import run_case


def test_subject_probe_requires_the_qualified_subject(monkeypatch, lexicon):
    from immich_memories.conformance import lexical_cases as module

    def reply(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        answer = (
            {"reason": "fixture", "choices": ["cat", "dog"]}
            if "mainly show" in prompt
            else {"reason": "fixture", "choice": "it narrows which ones belong"}
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    # WHY: public dictionary data and the external provider are the two boundaries.
    monkeypatch.setattr(module, "load_wordnet", lambda _: lexicon)
    monkeypatch.setattr(
        httpx.AsyncClient, "_transport_for_url", lambda *_: httpx.MockTransport(reply)
    )
    checks = lexical_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == "free-text qualified subject"))
    assert result.valid, result.quality
    assert result.calls == 6


def test_place_probe_rejects_a_generic_place_answer(monkeypatch, lexicon):
    from immich_memories.conformance import lexical_cases as module

    # WHY: replace only public dictionary data and provider HTTP.
    monkeypatch.setattr(module, "load_wordnet", lambda _: lexicon)
    answer = {"reason": "fixture", "choice": "any of that kind"}
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = lexical_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == "free-text particular place"))
    assert result.called and not result.valid
    assert "particular" in result.quality


def test_occasion_probe_accepts_only_one_occasion(monkeypatch, lexicon):
    from immich_memories.conformance import lexical_cases as module

    # WHY: public dictionary and provider are external to the question being validated.
    monkeypatch.setattr(module, "load_wordnet", lambda _: lexicon)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"reason": "fixture", "choice":"one single occasion"}'
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = lexical_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == "free-text one occasion"))
    assert result.valid, result.quality
    assert result.calls == 3


def test_names_probe_retains_kitten_as_a_cat(monkeypatch, lexicon):
    from immich_memories.conformance import lexical_cases as module

    # WHY: use a tiny public dictionary fixture and a deterministic provider HTTP answer.
    monkeypatch.setattr(module, "load_wordnet", lambda _: lexicon)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"reason": "fixture", "choices":["kitten"]}'},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = lexical_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == "free-text other names"))
    assert result.valid, result.quality
    assert result.calls == 3


def test_person_probe_resolves_two_people_with_the_same_first_name(monkeypatch, lexicon):
    from immich_memories.conformance import lexical_cases as module

    # WHY: public dictionary and provider HTTP are the only external dependencies.
    monkeypatch.setattr(module, "load_wordnet", lambda _: lexicon)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"reason": "fixture", "choice":"Avery Example (cousin)"}'
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = lexical_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == "free-text ambiguous person"))
    assert result.valid, result.quality
    assert result.calls == 3


def test_pool_probe_keeps_only_requested_black_cats(monkeypatch, lexicon):
    from immich_memories.conformance import lexical_cases as module

    def reply(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "who" in prompt and "what" in prompt and "when" in prompt:
            answer = {"what": ["black cats"], "who": [], "where": [], "when": []}
        elif "mainly show" in prompt:
            answer = {"reason": "fixture", "choices": ["cats"]}
        elif "quality word" in prompt:
            answer = {"reason": "fixture", "choice": "it narrows which ones belong"}
        elif "main subject (subject)" in prompt:
            answer = {"reason": "fixture", "choice": "an animal"}
        else:
            answer = {"reason": "fixture", "choices": []}
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    # WHY: the corpus fixture and HTTP response replace external data, not pool logic.
    monkeypatch.setattr(module, "load_wordnet", lambda _: lexicon)
    monkeypatch.setattr(
        httpx.AsyncClient, "_transport_for_url", lambda *_: httpx.MockTransport(reply)
    )
    checks = lexical_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == "free-text matching pool"))
    assert result.valid, result.quality
    assert result.calls >= 3
