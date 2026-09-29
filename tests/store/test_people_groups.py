"""Saved people expressions: a label `generate --group` resolves like `--people-expression`.

Every person and label here is invented.
"""

from __future__ import annotations

import copy

import pytest
import yaml

from immich_memories.api.person_expression import PersonExpression
from immich_memories.people.groups import add_group, group_expression, list_groups, remove_group
from immich_memories.people.transfer import export_yaml, import_document, parse_yaml

_TWO_KIDS = PersonExpression.parse('"id-kit" OR "id-rowan"')

_WITH_GROUP = {
    "version": 1,
    "people": [
        {
            "ids": ["id-kit"],
            "name": "Kit Example",
            "birth_date": None,
            "inferred": {"tier": "event", "counts_reliable": True, "evidence": {}, "links": []},
            "confirmed": {"role": None, "links": [], "notes": None},
        },
    ],
    "groups": [
        {"label": "kids", "expression": {"any": [{"person": "id-kit"}, {"person": "id-rowan"}]}}
    ],
}


def test_a_saved_group_round_trips_through_the_store(store):
    add_group(store, "kids", _TWO_KIDS)

    (saved,) = list_groups(store)
    assert saved.label == "kids"
    assert saved.expression == _TWO_KIDS


def test_group_expression_resolves_the_saved_label(store):
    add_group(store, "kids", _TWO_KIDS)

    assert group_expression(store, "kids") == _TWO_KIDS


def test_group_expression_names_the_known_labels_when_the_label_is_unknown(store):
    add_group(store, "kids", _TWO_KIDS)

    with pytest.raises(ValueError, match="kids"):
        group_expression(store, "cousins")


def test_group_expression_says_none_saved_yet_on_an_empty_registry(store):
    with pytest.raises(ValueError, match="none saved yet"):
        group_expression(store, "kids")


def test_a_label_already_in_use_is_refused(store):
    add_group(store, "kids", _TWO_KIDS)

    with pytest.raises(ValueError, match="already exists"):
        add_group(store, "kids", PersonExpression.parse('"id-kit"'))

    assert [saved.label for saved in list_groups(store)] == ["kids"]


def test_removing_an_unknown_label_is_refused(store):
    with pytest.raises(ValueError, match="no saved group"):
        remove_group(store, "kids")


def test_remove_group_drops_only_that_label_and_keeps_the_people(store):
    add_group(store, "kids", _TWO_KIDS)
    add_group(store, "cousins", PersonExpression.parse('"id-rowan"'))

    remove_group(store, "kids")

    assert [saved.label for saved in list_groups(store)] == ["cousins"]


def test_a_registry_with_no_groups_exports_with_no_groups_key(store):
    import_document(store, {"version": 1, "people": []})

    assert "groups" not in yaml.safe_load(export_yaml(store))


def test_groups_round_trip_byte_identical_through_export_and_import(store):
    import_document(store, copy.deepcopy(_WITH_GROUP))
    exported = export_yaml(store)

    import_document(store, parse_yaml(exported), replace=True)

    assert export_yaml(store) == exported
    assert yaml.safe_load(exported)["groups"] == _WITH_GROUP["groups"]


def test_import_refuses_a_duplicate_group_label(store):
    document = copy.deepcopy(_WITH_GROUP)
    document["groups"].append({"label": "kids", "expression": {"person": "id-rowan"}})

    with pytest.raises(Exception, match="listed twice"):
        import_document(store, document)


def test_import_refuses_a_malformed_group_expression(store):
    document = copy.deepcopy(_WITH_GROUP)
    document["groups"][0]["expression"] = {"nonsense": True}

    with pytest.raises(Exception, match="groups\\[0\\]"):
        import_document(store, document)
