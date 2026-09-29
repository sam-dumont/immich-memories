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

    # WHY: only the external provider response is fixed; title prompting and parsing stay real.
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
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
    )
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    result = run_case(cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))[0])
    assert result.called and result.valid
    assert result.calls == 1
    assert result.tokens == 25
    assert "titles.llm_titles:generate_title_with_llm" in result.observed


def test_command_lists_uncovered_sites_without_using_a_library(tmp_path, monkeypatch, capsys):
    from immich_memories.conformance import __main__ as command

    config = tmp_path / "provider.yaml"
    config.write_text("advanced:\n  llm:\n    model: fixture\n")
    # WHY: coverage must fail even if the provider returns a valid result; no paid call here.
    monkeypatch.setattr(command, "cases", lambda _llm: ())
    assert command.main(["--config", str(config)]) == 1
    assert "Uncovered call sites:" in capsys.readouterr().out


def test_every_model_call_site_is_covered_or_explicitly_pending():
    import json
    from pathlib import Path

    from immich_memories.config_models_llm import LLMConfig
    from immich_memories.conformance.cases import cases

    root = Path(__file__).parents[1] / "src" / "immich_memories"
    covered = set().union(*(case.sites for case in cases(LLMConfig(model="fixture"))))
    pending = set(json.loads((root / "conformance" / "pending.json").read_text()))
    assert not covered & pending
    assert discover_sites(root) == covered | pending, "New LLM call site needs a conformance case"
