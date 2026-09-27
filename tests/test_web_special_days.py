"""The catalogue's days, as the brief offers them: anniversaries due first, then the rest."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from immich_memories.web.library import special_days_catalogue, today
from tests.web_api_fixtures import api_client, config_in


def _row(day: str, title: str, what: str = "") -> dict:
    return {"day": day, "title": title, "subtitle": "", "what": what, "photos": 40}


def test_due_anniversaries_lead_and_unnamed_days_are_not_offered(tmp_path: Path):
    catalogue = tmp_path / "special-days.json"
    catalogue.write_text(
        json.dumps(
            [
                _row("2019-03-02", "A race"),
                _row("2016-06-12", "The wedding"),
                _row("2021-06-10", "", what="a garden party"),
                _row("2020-01-01", "", what=""),
                {"unjudged": "2018-06-11", "photos": 3},
            ]
        )
    )
    client = api_client(config_in(tmp_path))
    client.app.dependency_overrides[special_days_catalogue] = lambda: catalogue
    # WHY: "due" is relative to the day the brief opens; pin it.
    client.app.dependency_overrides[today] = lambda: date(2026, 6, 11)

    days = client.get("/api/v1/special-days").json()

    assert [(d["day"], d["name"], d["years_ago"]) for d in days] == [
        ("2016-06-12", "The wedding", 10),
        ("2021-06-10", "a garden party", 5),
        ("2019-03-02", "A race", None),
    ]


def test_no_catalogue_is_an_empty_list(tmp_path: Path):
    client = api_client(config_in(tmp_path))
    client.app.dependency_overrides[special_days_catalogue] = lambda: tmp_path / "missing.json"

    assert client.get("/api/v1/special-days").json() == []
