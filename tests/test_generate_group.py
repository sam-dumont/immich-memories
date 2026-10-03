"""`generate --group` resolves a saved label the way `--people-expression` resolves text.

The Immich boundary is the same roster-only fake `test_people_expression_cli.py` uses:
--group's job is to hand the saved expression to the exact code path --people-expression
already walks, so this only has to prove that hand-off, not re-prove resolution itself.
"""

from __future__ import annotations

import pytest

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


@pytest.mark.parametrize(
    "names",
    [["Adult A", "Adult B"], ["", "Adult B"], ["", ""], ["Same", "Same"], ["  ", "Adult B"]],
)
def test_saved_canonical_people_are_named_in_the_film_title(tmp_path, names):
    from immich_memories.filename_builder import build_title_person_name
    from immich_memories.people.transfer import import_document

    first = "00000000-0000-4000-8000-000000000001"
    second = "00000000-0000-4000-8000-000000000002"
    import_document(
        open_store(),
        {
            "version": 1,
            "people": [
                {"ids": [first, "a"], "name": names[0]},
                {"ids": [second, "b"], "name": names[1]},
            ],
        },
    )
    expression = PersonExpression.parse(f'"{first}" OR "{second}"')
    add_group(open_store(), "grownups", expression)
    result, _, pipeline = invoke(
        tmp_path,
        [
            "--memory-type",
            "multi_person",
            "--year",
            "2024",
            "--no-music",
            "--no-live-photos",
            "--group",
            "grownups",
        ],
        Client(),
    )
    assert result.exit_code == 0, (result.output, result.exception)
    kwargs = pipeline.call_args.kwargs
    title_name = build_title_person_name(
        "multi_person", kwargs["memory_preset_params"], None, use_first_name_only=False
    )
    expected = " · ".join(name.strip() for name in names if name.strip()) or None
    assert title_name == expected
    assert kwargs["person_names"] == [first, second]
    assert kwargs["memory_preset_params"]["person_names"] == [first, second]
    assert kwargs["memory_preset_params"]["person_expression"] == expression.to_dict()
    from immich_memories.analysis.editorial_runtime import EditorialRunContext

    context = EditorialRunContext(
        key="group-title",
        label="Group film",
        product="multi_person",
        date_ranges=tuple(kwargs["date_ranges"]),
        target_seconds=60,
        artifact_dir=tmp_path,
        people=tuple(kwargs["person_names"]),
        person_expression=expression,
    )
    assert context.people == expression.leaf_values


def test_a_person_selected_by_canonical_id_is_named_in_the_title(tmp_path):
    from immich_memories.filename_builder import build_title_person_name
    from immich_memories.people.transfer import import_document

    identity = "00000000-0000-4000-8000-000000000003"
    import_document(
        open_store(),
        {
            "version": 1,
            "people": [
                {"ids": [identity, "a"], "name": "Adult A"},
            ],
        },
    )
    result, _, pipeline = invoke(
        tmp_path,
        ["--year", "2024", "--person", identity, "--no-music", "--no-live-photos"],
        Client(),
    )
    assert result.exit_code == 0, (result.output, result.exception)
    kwargs = pipeline.call_args.kwargs
    title_name = build_title_person_name(
        "person_spotlight",
        kwargs["memory_preset_params"],
        kwargs["person_names"][0],
        use_first_name_only=False,
    )
    assert title_name == "Adult A"
    assert kwargs["person_names"] == [identity]
    assert {asset.id for asset in kwargs["assets"]} == {
        "VIDEO-a-child",
        "VIDEO-adults-only",
    }


@pytest.mark.parametrize("anonymous", [False, True])
def test_hosted_title_uses_display_names_without_changing_nested_scope(anonymous):
    from datetime import datetime

    from immich_memories.config_loader import Config
    from immich_memories.generate_privacy import anonymize_preset_params
    from immich_memories.timeperiod import DateRange
    from immich_memories.titles.film_title import resolve_film_title

    expression = PersonExpression.parse('("id-a" OR "id-b") AND "id-c"')
    params = {
        "person_expression": expression.to_dict(),
        "person_names": list(expression.leaf_values),
        "person_display_names": {"id-a": "Adult A", "id-b": "Adult B", "id-c": "Child"},
    }
    if anonymous:
        params = anonymize_preset_params(params)
    seen = []

    # WHY: ask is the external hosted title-provider boundary; no network call is made.
    def ask(**kwargs):
        seen.append(kwargs)
        return None

    config = Config(llm={"enabled": True, "provider": "openai-compatible", "model": "example"})
    resolve_film_title(
        enabled=True,
        title_override=None,
        clips=[],
        config=config,
        memory_type="multi_person",
        date_range=DateRange(datetime(2024, 1, 1), datetime(2024, 12, 31)),
        person_names=list(expression.leaf_values),
        memory_preset_params=params,
        ask=ask,
    )
    assert seen[0]["person_names"] == list(params["person_display_names"].values())
    assert "id-" not in seen[0]["facts"].people_condition
    assert params["person_expression"] == expression.to_dict()
    assert params["person_names"] == list(expression.leaf_values)
    if anonymous:
        assert not {"Adult A", "Adult B", "Child"} & set(seen[0]["person_names"])


def test_duplicate_display_names_do_not_borrow_another_persons_birth_date():
    from datetime import date

    from immich_memories.people.transfer import import_document
    from immich_memories.titles.llm_titles import people_title_facts

    import_document(
        open_store(),
        {
            "version": 1,
            "people": [
                {"ids": ["example-a"], "name": "Same", "birth_date": "1980-01-01"},
                {"ids": ["example-b"], "name": "Same", "birth_date": "1990-01-01"},
            ],
        },
    )
    facts = people_title_facts(["Same", "Same"], date(2024, 1, 1), date(2024, 12, 31))
    assert "People in the film: 2" in facts
    assert facts.count("birth date unknown") == 2
    assert "1980" not in facts and "1990" not in facts


def test_anonymized_template_uses_masked_display_labels(tmp_path):
    from datetime import date

    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_privacy import anonymize_preset_params
    from immich_memories.generate_settings import build_title_settings

    expression = PersonExpression.parse('"id-a" OR "id-b"')
    original = {
        "person_expression": expression.to_dict(),
        "person_names": ["id-a", "id-b"],
        "person_display_names": {"id-a": "Adult A", "id-b": "Adult B"},
    }
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "out.mp4",
        config=Config(),
        memory_type="multi_person",
        date_start=date(2024, 1, 1),
        date_end=date(2024, 12, 31),
        memory_preset_params=anonymize_preset_params(original),
    )
    settings = build_title_settings(params, params.config, [])
    assert settings is not None
    assert "Adult" not in settings.person_name and "id-" not in settings.person_name
    assert params.memory_preset_params["person_expression"] == original["person_expression"]
    assert original["person_display_names"] == {"id-a": "Adult A", "id-b": "Adult B"}
