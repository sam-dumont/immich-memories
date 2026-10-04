"""A configured reader that cannot be reached says so once, instead of failing silently."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from immich_memories.analysis import llm_query
from immich_memories.config_models_llm import LLMConfig


def _ask(config: LLMConfig) -> None:
    with pytest.raises(httpx.HTTPError):
        asyncio.run(llm_query.query_llm("hello", config))


def test_unreachable_reader_logs_one_warning_naming_the_host(caplog):
    # 127.0.0.1:9 refuses connections, a real unreachable reader with no mock.
    config = LLMConfig(enabled=True, provider="ollama", base_url="http://127.0.0.1:9", model="m")
    with caplog.at_level(logging.WARNING, logger="immich_memories"):
        _ask(config)
        _ask(config)

    warnings = [r for r in caplog.records if "Reader unreachable" in r.getMessage()]
    assert len(warnings) == 1
    assert "127.0.0.1:9" in warnings[0].getMessage()
    assert warnings[0].levelno == logging.WARNING
