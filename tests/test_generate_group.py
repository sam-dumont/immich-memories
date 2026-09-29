"""`generate --group` resolves a saved label the way `--people-expression` resolves text.

The Immich boundary is the same roster-only fake `test_people_expression_cli.py` uses:
--group's job is to hand the saved expression to the exact code path --people-expression
already walks, so this only has to prove that hand-off, not re-prove resolution itself.
"""

from __future__ import annotations

from immich_memories.api.person_expression import PersonExpression
from immich_memories.db import open_store
from immich_memories.people.groups import add_group
from tests.test_people_expression_cli import EXPRESSION, PEOPLE, TEXT, Client, invoke


def test_group_reaches_the_pipeline_exactly_as_the_same_expression_typed_out(tmp_path):
    add_group(open_store(), "grownups-and-child", PersonExpression.parse(TEXT))
    client = Client()

    result, _, pipeline = invoke(
        tmp_path,
        [
            "--memory-type",
            "multi_person",
            "--year",
            "2024",
            "--include-photos",
            "--no-live-photos",
            "--no-music",
            "--group",
            "grownups-and-child",
        ],
        client,
    )

    assert result.exit_code == 0, (result.output, result.exception)
    kwargs = pipeline.call_args.kwargs
    assert kwargs["memory_preset_params"]["person_expression"] == EXPRESSION.to_dict()
    assert kwargs["person_names"] == list(EXPRESSION.leaf_values)


def test_an_unknown_group_label_is_a_usage_error_before_any_picture_is_read(tmp_path):
    client = Client()

    result, _, pipeline = invoke(
        tmp_path, ["--year", "2024", "--group", "nobody-saved-this"], client
    )

    assert result.exit_code == 2, result.output
    assert "nobody-saved-this" in result.output
    assert client.calls == []
    pipeline.assert_not_called()


def test_group_and_people_expression_together_is_refused(tmp_path):
    add_group(open_store(), "kids", PersonExpression.parse('"c"'))
    client = Client(PEOPLE)

    result, _, pipeline = invoke(
        tmp_path,
        ["--year", "2024", "--group", "kids", "--people-expression", TEXT],
        client,
    )

    assert result.exit_code == 2, result.output
    assert "not both" in result.output
    pipeline.assert_not_called()


def test_group_and_person_together_is_refused(tmp_path):
    add_group(open_store(), "kids", PersonExpression.parse('"c"'))
    client = Client(PEOPLE)

    result, _, pipeline = invoke(
        tmp_path,
        ["--year", "2024", "--group", "kids", "--person", "Adult A"],
        client,
    )

    assert result.exit_code == 2, result.output
    assert "separately" in result.output
    pipeline.assert_not_called()
