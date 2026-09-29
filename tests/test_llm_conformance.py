"""A provider check must expose skipped features and discover new call sites."""

from immich_memories.conformance.inventory import discover_sites


def test_new_llm_call_sites_are_discovered_even_through_an_import_alias(tmp_path):
    source = tmp_path / "new_feature.py"
    source.write_text(
        "from immich_memories.analysis.llm_query import query_llm as ask_model\n"
        "async def new_feature(config):\n"
        "    return await ask_model('synthetic prompt', config)\n"
    )
    assert discover_sites(tmp_path) == {"new_feature:new_feature"}


def test_a_valid_fallback_is_not_reported_as_a_provider_success():
    from immich_memories.conformance.runtime import Case, run_case

    result = run_case(Case("fallback", lambda: "valid local fallback", frozenset()))
    assert result.calls == 0
    assert result.called is False
    assert result.valid is False
    assert result.quality == "feature made no provider request"


def test_title_probe_measures_the_real_feature_transport_and_parse(monkeypatch):
    import httpx

    from immich_memories.config_models_llm import LLMConfig
    from immich_memories.conformance.cases import cases
    from immich_memories.conformance.runtime import run_case

    def reply(request):
        import json

        prompt = json.loads(request.content)["messages"][0]["content"]
        assert "chess tournament" in prompt.lower(), "fixture fact never reached the provider"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"title":"Chess tournament"}'},
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    # WHY: only the external provider response is fixed; title prompting and parsing stay real.
    transport = httpx.MockTransport(reply)
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    result = run_case(cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))[0])
    assert result.called and result.valid
    assert result.calls == 1
    assert result.tokens == 25
    assert result.usage["llm_prompt_tokens"] == 20
    assert result.usage["llm_completion_tokens"] == 5
    assert "titles.llm_titles:generate_title_with_llm" in result.observed


def test_command_lists_uncovered_sites_without_using_a_library(tmp_path, monkeypatch, capsys):
    from immich_memories.conformance import __main__ as command

    config = tmp_path / "provider.yaml"
    config.write_text("advanced:\n  llm:\n    model: fixture\n")
    # WHY: coverage must fail even if the provider returns a valid result; no paid call here.
    monkeypatch.setattr(command, "cases", lambda _llm: ())
    assert command.main(["--config", str(config)]) == 1
    assert "Uncovered call sites:" in capsys.readouterr().out


def test_every_model_call_site_has_a_conformance_case():
    from pathlib import Path

    from immich_memories.config_models_llm import LLMConfig
    from immich_memories.conformance.cases import cases

    root = Path(__file__).parents[1] / "src" / "immich_memories"
    covered = set().union(*(case.sites for case in cases(LLMConfig(model="fixture"))))
    assert discover_sites(root) == covered, "New LLM call site needs a conformance case"


def test_nested_asking_function_is_not_misattributed_to_its_factory(tmp_path):
    (tmp_path / "feature.py").write_text(
        "def factory():\n"
        "    def ask():\n"
        "        return ask_llm_image(config, image)\n"
        "    return ask\n"
    )
    assert discover_sites(tmp_path) == {"feature:factory.ask"}


def test_free_text_asker_adapter_is_discovered(tmp_path):
    (tmp_path / "feature.py").write_text(
        "def read(asker):\n    return asker.ask('synthetic question')\n"
    )
    assert discover_sites(tmp_path) == {"feature:read"}


def test_probe_preserves_private_wire_evidence_without_headers(tmp_path, monkeypatch):
    import asyncio
    import json

    import httpx

    from immich_memories.analysis.llm_query import query_llm
    from immich_memories.config_models_llm import LLMConfig
    from immich_memories.conformance.runtime import Case, run_case

    config = LLMConfig(
        model="fixture", base_url="http://localhost:43210/v1", api_key="fixture-secret"
    )
    # WHY: provider HTTP is the only substituted boundary.
    monkeypatch.setattr(
        httpx.AsyncClient,
        "_transport_for_url",
        lambda *_: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {"finish_reason": "stop", "message": {"content": "synthetic reply"}}
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                },
            )
        ),
    )
    case = Case(
        "wire evidence", lambda: asyncio.run(query_llm("synthetic prompt", config)), frozenset()
    )
    result = run_case(case, evidence_dir=tmp_path)
    assert result.valid
    files = list(tmp_path.rglob("*.private.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text())
    assert saved["response"]["choices"][0]["message"]["content"] == "synthetic reply"
    assert saved["request"]["messages"][0]["content"] == "synthetic prompt"
    assert "fixture-secret" not in files[0].read_text()


def test_command_saves_incremental_results_without_provider_configuration(
    tmp_path, monkeypatch, capsys
):
    import json

    from immich_memories.conformance import __main__ as command
    from immich_memories.conformance.runtime import Case

    config = tmp_path / "provider.yaml"
    config.write_text("llm:\n  model: fixture\n  api_key: fixture-secret\n")
    # WHY: a synthetic local result checks command persistence without buying a provider call.
    monkeypatch.setattr(
        command, "cases", lambda _: (Case("offline", lambda: "fallback", frozenset()),)
    )
    out = tmp_path / "evidence"
    assert command.main(["--config", str(config), "--output", str(out)]) == 1
    saved = json.loads((out / "results.private.json").read_text())
    assert saved[0]["name"] == "offline" and saved[0]["valid"] is False
    assert "fixture-secret" not in (out / "results.private.json").read_text()
    assert "offline" in capsys.readouterr().out


def test_trip_title_probe_requires_route_classification(monkeypatch):
    import httpx

    from immich_memories.config_models_llm import LLMConfig
    from immich_memories.conformance.cases import cases
    from immich_memories.conformance.runtime import run_case

    # WHY: only the external model response is fixed; the trip prompt and parser stay real.
    monkeypatch.setattr(
        httpx.AsyncClient,
        "_transport_for_url",
        lambda *_: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": '{"title":"Iceland road trip","trip_type":"road_trip","map_mode":"overnight_stops","map_mode_reason":"A driving route"}'
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )
        ),
    )
    checks = cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "trip title and route"))
    assert result.valid, result.quality
    assert result.calls == 1


def test_people_title_probe_uses_only_its_synthetic_people_store(monkeypatch):
    import httpx

    from immich_memories.config_models_llm import LLMConfig
    from immich_memories.conformance.cases import cases
    from immich_memories.conformance.runtime import run_case

    # WHY: provider response only; the people prompt reads a real temporary store.
    monkeypatch.setattr(
        httpx.AsyncClient,
        "_transport_for_url",
        lambda *_: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '{"title":"Avery in 2030"}'},
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )
        ),
    )
    checks = cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "people title"))
    assert result.valid, result.quality
    assert result.calls == 1


def test_failed_http_attempt_does_not_claim_zero_billed_tokens(monkeypatch):
    import asyncio

    import httpx

    from immich_memories.analysis.llm_query import query_llm
    from immich_memories.config_models_llm import LLMConfig
    from immich_memories.conformance.runtime import Case, run_case

    # WHY: an authorization response has no usage report; only provider HTTP is substituted.
    monkeypatch.setattr(
        httpx.AsyncClient,
        "_transport_for_url",
        lambda *_: httpx.MockTransport(
            lambda _: httpx.Response(401, json={"error": {"message": "Unauthorized"}})
        ),
    )
    config = LLMConfig(model="fixture", base_url="http://localhost:43210/v1")
    result = run_case(
        Case("unauthorized", lambda: asyncio.run(query_llm("synthetic", config)), frozenset())
    )
    assert result.calls == 1 and not result.valid
    assert result.tokens is None
