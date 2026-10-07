"""The settings page tells the editor what each setting accepts (#2234)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from immich_memories.config_loader import Config, load_config, set_config
from immich_memories.config_sources import describe_settings
from immich_memories.settings_edit import field_type


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("IMMICH_MEMORIES_SECRET_KEY", "k" * 40)
    path = tmp_path / "config.yaml"
    path.write_text("")
    load_config(path)
    yield path
    set_config(None)


@pytest.fixture
def rows(config_path: Path) -> dict[str, dict]:
    from immich_memories.web.server import create_app

    body = TestClient(create_app(), follow_redirects=False).get("/api/v1/settings").json()
    return {row["key"]: row for section in body["sections"] for row in section["settings"]}


def _values(row: dict) -> list[str]:
    return [choice["value"] for choice in row["input"]["choices"]]


def test_the_codec_is_a_choice_with_readable_english_labels(rows):
    codec = rows["output.codec"]["input"]

    assert codec["kind"] == "choice"
    assert {c["value"]: c["label"] for c in codec["choices"]}["h264"] == "H.264, software (libx264)"


def test_the_tier_offers_its_declared_list_and_never_the_legacy_nas(rows):
    assert _values(rows["tier"]) == ["auto", "basic", "gpu", "full"]


def test_an_optional_choice_has_an_empty_choice(rows):
    assert _values(rows["preset"])[0] == ""


def test_a_number_carries_its_bounds(rows):
    crf = rows["output.crf"]["input"]

    assert (crf["kind"], crf["min"], crf["max"]) == ("number", 0, 51)


def test_a_boolean_and_a_secret_are_described(rows):
    assert rows["automation.enabled"]["input"]["kind"] == "bool"
    assert rows["immich.api_key"]["input"]["kind"] == "secret"


def test_a_number_or_auto_is_text_with_a_hint(rows):
    workers = rows["analysis.source_prepare_workers"]["input"]

    assert workers["kind"] == "text"
    assert "auto" in workers["hint"]


def test_every_literal_and_enum_setting_comes_with_choices(rows):
    import enum
    import typing

    def is_choice(annotation) -> bool:
        args = typing.get_args(annotation)
        if typing.get_origin(annotation) is typing.Literal:
            return True
        if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
            return True
        return (
            typing.get_origin(annotation) is not typing.Annotated
            and any(is_choice(a) for a in args if a is not type(None))
            and len([a for a in args if a is not type(None)]) == 1
        )

    chosen = [e.key for e in describe_settings(Config()) if is_choice(field_type(e.key))]

    assert chosen, "the walk found no choice settings at all"
    for key in chosen:
        assert rows[key]["input"]["kind"] == "choice", key
        assert rows[key]["input"]["choices"], key


def test_a_blank_optional_setting_saves_as_not_set(config_path):
    from immich_memories.config_loader import get_config
    from immich_memories.web.server import create_app

    client = TestClient(create_app(), follow_redirects=False)
    assert client.post("/api/v1/settings", json={"values": {"output.crf": "20"}}).status_code == 200

    response = client.post("/api/v1/settings", json={"values": {"output.crf": ""}})

    assert response.status_code == 200
    assert get_config(reload=True).output.crf is None


def test_a_value_outside_the_list_is_refused_with_the_list(config_path):
    from immich_memories.web.server import create_app

    client = TestClient(create_app(), follow_redirects=False)

    response = client.post("/api/v1/settings", json={"values": {"output.codec": "av1"}})

    assert response.status_code == 422
    assert "h264" in response.json()["detail"]
