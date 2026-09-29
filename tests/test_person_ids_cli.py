"""`generate --person` takes a name or an id (#1500, owner ruling 2026-09-29).

A name several store people carry picks all of them and warns, listing each one's id; an
id (UUID-shaped) picks exactly one person. The Immich server is the two-account fake of
`tests/household_fake.py`; the people store is the test's real isolated store.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from immich_memories.db import open_store
from immich_memories.people.transfer import import_document
from tests.household_fake import PRIMARY_KEY, FakeHousehold, immich_config, picture

ALEX_ONE = "11111111-1111-4111-8111-111111111111"
ALEX_TWO = "22222222-2222-4222-8222-222222222222"
ALEX_TWO_PARTNER = "33333333-3333-4333-8333-333333333333"
ROBIN = "44444444-4444-4444-8444-444444444444"
NOBODY = "99999999-9999-4999-8999-999999999999"


def _person(ids: list[str], name: str, accounts: dict[str, str] | None = None) -> dict:
    return {
        "ids": ids,
        **({"accounts": accounts} if accounts else {}),
        "name": name,
        "birth_date": None,
        "inferred": {"tier": "inner", "counts_reliable": True, "evidence": {}, "links": []},
        "confirmed": {"role": None, "links": [], "notes": None},
    }


# Two different people the owner named Alex; the second also has a partner-account cluster.
REGISTRY = {
    "version": 1,
    "people": [
        _person([ALEX_ONE], "Alex"),
        _person([ALEX_TWO, ALEX_TWO_PARTNER], "Alex", {ALEX_TWO_PARTNER: "partner"}),
    ],
}


@pytest.fixture
def immich(monkeypatch) -> FakeHousehold:
    import_document(open_store(), REGISTRY)
    server = FakeHousehold(
        library={
            PRIMARY_KEY: [
                picture("p-alex-one", "primary", 2, (ALEX_ONE,)),
                picture("p-alex-two", "primary", 3, (ALEX_TWO,)),
                picture("p-robin", "primary", 4, (ROBIN,)),
            ]
        },
        roster={
            PRIMARY_KEY: [
                {"id": ALEX_ONE, "name": "Alex"},
                {"id": ALEX_TWO, "name": "Alex"},
                {"id": ROBIN, "name": "Robin"},
            ]
        },
    )
    return server.install(monkeypatch)


def _generate(tmp_path, *people):
    from immich_memories.cli import main

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"immich": immich_config()}))
    with (
        # WHY: init_config_dir would create a real config dir under the user's home.
        patch("immich_memories.cli.init_config_dir"),
        # WHY: the pipeline renders and uploads; the test inspects what it was handed.
        patch(
            "immich_memories.cli.generate.run_pipeline_and_generate",
            return_value=(tmp_path / "out.mp4", False, None),
        ) as pipeline,
    ):
        result = CliRunner().invoke(
            main,
            [
                *("-c", str(config), "generate", "--quiet", "--year", "2025", "--month", "6"),
                *("--include-photos", "--no-live-photos", "--no-music", *people),
            ],
        )
    photos = (
        sorted(photo.id for photo in pipeline.call_args.kwargs["photo_assets"])
        if pipeline.called
        else None
    )
    return result, photos


def test_a_name_two_store_people_carry_picks_both_and_says_how_to_pick_one(tmp_path, immich):
    result, photos = _generate(tmp_path, "--person", "Alex")

    assert result.exit_code == 0, result.output
    assert photos == ["p-alex-one", "p-alex-two"]
    assert "'Alex' is 2 people in the people store" in result.output
    assert f"Alex (id {ALEX_ONE}; primary: {ALEX_ONE})" in result.output
    assert f"Alex (id {ALEX_TWO}; primary: {ALEX_TWO}; partner: {ALEX_TWO_PARTNER})" in (
        result.output
    )
    assert "Use --person <id> to choose one." in result.output


def test_a_store_id_picks_that_person_alone(tmp_path, immich):
    result, photos = _generate(tmp_path, "--person", ALEX_ONE)

    assert result.exit_code == 0, result.output
    assert photos == ["p-alex-one"]
    assert "people in the people store" not in result.output


def test_an_immich_id_picks_the_store_person_whose_alias_it_is(tmp_path, immich):
    # The partner's cluster names the second Alex; a primary run reads that Alex's primary face.
    result, photos = _generate(tmp_path, "--person", ALEX_TWO_PARTNER)

    assert result.exit_code == 0, result.output
    assert photos == ["p-alex-two"]


def test_an_immich_id_the_store_does_not_hold_is_a_plain_face(tmp_path, immich):
    result, photos = _generate(tmp_path, "--people-expression", f'"{ROBIN}" OR "{ALEX_ONE}"')

    assert result.exit_code == 0, result.output
    assert photos == ["p-alex-one", "p-robin"]


def test_an_id_nobody_holds_is_a_usage_error_naming_it(tmp_path, immich):
    result, photos = _generate(tmp_path, "--person", NOBODY)

    assert result.exit_code == 2
    assert f"No person with id {NOBODY}" in result.output
    assert photos is None
