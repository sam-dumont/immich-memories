"""With a reader model, a trip that changes where it stays is one story per leg (#1563)."""

from __future__ import annotations

import json
from datetime import date

from tests.editorial_film_fixtures import (
    FilmJudge,
    _json_after,
    film_source,
    home_days,
    trip_days,
)
from tests.test_editorial_duration_planner_integration import run

MAY = (date(2030, 5, 1), date(2030, 5, 31))
# Far from home (45, 5), and about 185 km from each other.
TRAIL = (43.0, 9.0, "Trailhead", "Farland")
CITY = (44.66, 9.0, "Big City", "Farland")


class OneStoryJudge(FilmJudge):
    """The reader files every day of the period as one story, as it did on the reported trip."""

    def answer(self, stage, prompt):
        if stage.startswith("story-understanding"):
            cards = _json_after(prompt, "remarkable, maybe or background)\n")
            return json.dumps(
                {
                    "thesis": "One journey.",
                    "about": [],
                    "stories": [
                        {
                            "title": "The journey",
                            "episodes": [c["episode"] for c in cards],
                            "purpose": "The journey",
                        }
                    ],
                    "uncertainties": [],
                }
            )
        return super().answer(stage, prompt)


def _days():
    return [
        *trip_days(date(2030, 5, 10), 5, where=TRAIL),
        *trip_days(date(2030, 5, 15), 3, where=CITY),
    ]


def _story_rows(plan):
    return [row for row in plan["story"]["episodes"] if row.get("day_episodes")]


def test_a_trip_inside_a_film_is_one_story_per_leg(tmp_path):
    days = [*home_days(date(2030, 5, 1), 8), *_days(), *home_days(date(2030, 5, 19), 10)]
    plan = run(film_source(tmp_path, days, seconds=60, span=MAY), FilmJudge())

    trips = [row for row in plan["story"]["episodes"] if row.get("kind") == "trip"]
    assert sorted(len(row["day_episodes"]) for row in trips) == [3, 5]
    assert {"Trailhead", "Big City"} <= {
        place for row in trips for place in ("Trailhead", "Big City") if place in row["title"]
    }


def test_a_trip_film_splits_a_story_that_spans_two_legs(tmp_path):
    source = film_source(tmp_path, _days(), seconds=60, span=MAY, product="trip")
    plan = run(source, OneStoryJudge())

    assert sorted(len(row["day_episodes"]) for row in _story_rows(plan)) == [3, 5]
