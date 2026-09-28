"""A day verdict does not depend on unused display copy or truthy strings."""

import json
from unittest.mock import patch

import pytest

from immich_memories.analysis.special_day import ask_if_special
from immich_memories.automation.special_day_scan import scan_year
from immich_memories.config_models_llm import LLMConfig
from tests.annotation_rows import annotation_store
from tests.test_special_day_captions import _a_real_day, _verdict_response


@pytest.mark.parametrize(
    "display",
    [
        {
            "title": {"unused": True},
            "subtitle": None,
            "what": "An ordinary afternoon. " * 20,
            "window": "unused",
        },
        {},
    ],
    ids=["irrelevant", "absent"],
)
def test_an_explicit_negative_is_banked_without_validating_unused_display_copy(tmp_path, display):
    assets, captions = _a_real_day(captioned=30)
    reply = _verdict_response(json.dumps({"special": False, **display}))
    config = LLMConfig(model="day-reader", provider="ollama")
    # WHY: the provider is external; the public reader and its bank stay real.
    with patch("httpx.AsyncClient.post", return_value=reply) as post:
        first = ask_if_special(assets, config, captions=captions, judgments=annotation_store())
        repeated = ask_if_special(assets, config, captions=captions, judgments=annotation_store())

    assert first.judged and not first.special
    assert first.title == first.subtitle == first.what == ""
    assert first.window is None
    assert repeated == first
    assert post.call_count == 1


@pytest.mark.parametrize("banked", [False, True])
@pytest.mark.parametrize("subtitle", [{"subtitle": None}, {}], ids=["null", "omitted"])
def test_a_positive_day_can_have_an_optional_subtitle(tmp_path, banked, subtitle):
    assets, captions = _a_real_day(captioned=30)
    reply = _verdict_response(
        json.dumps(
            {"special": True, "title": "A race", "what": "A race", "window": None, **subtitle}
        )
    )
    # WHY: only the provider response is simulated; title grounding and caching run normally.
    with patch("httpx.AsyncClient.post", return_value=reply) as post:
        verdict = ask_if_special(
            assets,
            LLMConfig(model="day-reader", provider="ollama"),
            captions=captions,
            judgments=annotation_store() if banked else None,
        )

    assert verdict.judged and verdict.special
    assert verdict.title == "A race"
    assert verdict.subtitle == ""
    assert post.call_count == 1


@pytest.mark.parametrize("route", ["facts", "captions", "banked"])
@pytest.mark.parametrize(
    "raw",
    [
        '{"special":"false","title":"A race","what":"A race"}',
        '{"special":1,"title":"A race","what":"A race"}',
        '{"special":null,"title":"A race","what":"A race"}',
        '{"special":false,"special":true,"title":"A race","what":"A race"}',
        '{"special":true,"title":null,"what":"A race"}',
        '{"special":true,"what":"A race"}',
        json.dumps({"special": True, "title": "A" * 91, "what": "A race"}),
        json.dumps({"special": True, "title": "A race", "what": "A" * 81}),
        '{"special":true,"title":"A race","subtitle":[],"what":"A race"}',
        '{"special":true,"title":"A race","what":"A race","extra":true}',
        '{"special":true,"title":"A race"',
    ],
)
def test_an_invalid_day_answer_stays_unjudged_on_every_route(tmp_path, route, raw):
    assets, captions = _a_real_day(captioned=30)
    if route == "facts":
        captions = {}
        for asset in assets:
            asset.llm_description = "People cross a finish line."
    # WHY: these are malformed provider replies, with no real inference or network access.
    with patch("httpx.AsyncClient.post", return_value=_verdict_response(raw)):
        verdict = ask_if_special(
            assets,
            LLMConfig(model="day-reader", provider="ollama"),
            captions=captions,
            judgments=annotation_store() if route == "banked" else None,
        )

    assert not verdict.judged and not verdict.special


def test_a_valid_negative_day_verdict_vetoes_the_months_proposed_occasion(tmp_path):
    assets, captions = _a_real_day(captioned=30)
    config = LLMConfig(model="day-reader", provider="ollama")
    # WHY: simulate the external model's month proposal and independent day rejection.
    replies = [
        _verdict_response('{"occasions":[{"run":"R1","what":"A race"}]}'),
        _verdict_response('{"special":false}'),
    ]
    with patch("httpx.AsyncClient.post", side_effect=replies) as post:
        found = scan_year(
            assets,
            llm_config=config,
            home=None,
            captions=captions,
            judgments=annotation_store(),
        )

    assert found == []
    assert post.call_count == 2
