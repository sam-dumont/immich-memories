"""D18: enumerate semantic misses and operational hits at the shared cache boundary."""

from dataclasses import replace

import pytest

from immich_memories.analysis.editorial_case import TextRequest
from immich_memories.config_models_llm import LLMConfig
from tests.annotation_rows import annotation_store


def request():
    return TextRequest(
        prompt='Contract: race memory. Evidence: F1 start; F2 finish. Return {"keep":[]}.',
        llm_config=LLMConfig(
            provider="openai-compatible",
            base_url="http://editor.test/v1",
            model="pinned-local-model",
            api_key="test-credential",
            thinking=True,
        ),
        judgments=annotation_store(),
        max_tokens=800,
        timeout_seconds=30,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"prompt": 'Contract: race memory. Evidence: F2 finish; F1 start. Return {"keep":[]}.'},
        {"prompt": 'Contract: training memory. Evidence: F1 start; F2 finish. Return {"keep":[]}.'},
        {"prompt": 'Contract: race memory. Evidence: F1 start; F2 finish. Return {"cut":[]}.'},
        {"max_tokens": 801},
        {"thinking": True},
        {"json_object": True},
    ],
)
def test_order_contract_schema_and_generation_changes_miss(change):
    original = request()
    assert replace(original, **change).judgment_key != original.judgment_key


@pytest.mark.parametrize(
    "change",
    [
        {"model": "another-model"},
        {"base_url": "http://another-editor.test/v1"},
        {"no_thinking_params": {"enable_thinking": False}},
        {"max_tokens_param": "max_completion_tokens"},
        {"drop_params": ["temperature"]},
        {"extra_params": {"do_sample": False}},
    ],
)
def test_model_endpoint_and_transport_dialect_changes_miss(change):
    original = request()
    config = original.llm_config.model_copy(update=change)
    assert replace(original, llm_config=config).judgment_key != original.judgment_key


def test_active_reasoning_configuration_is_part_of_the_identity():
    original = replace(request(), thinking=True)
    config = original.llm_config.model_copy(
        update={"thinking_params": {"reasoning_effort": "high"}}
    )
    assert replace(original, llm_config=config).judgment_key != original.judgment_key


def test_credentials_deadlines_and_storage_paths_do_not_change_the_answer_identity():
    original = request()
    changed = replace(
        original,
        llm_config=original.llm_config.model_copy(update={"api_key": "rotated-test-credential"}),
        judgments=annotation_store(),
        timeout_seconds=90,
    )
    assert changed.judgment_key == original.judgment_key
