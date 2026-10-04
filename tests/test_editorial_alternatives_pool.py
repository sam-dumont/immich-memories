"""A replacement's context names its own moment, never the refused carrier's."""

from __future__ import annotations

from immich_memories.analysis.editorial_story_planner import StorySelection
from immich_memories.analysis.editorial_story_reading import PeriodStory, StoryEpisode
from immich_memories.analysis.editorial_story_replacement_pool import alternatives_pool


def selection(carriers, alternatives_of, unfunded_pool=()):
    story = PeriodStory(
        thesis="",
        episodes=[
            StoryEpisode(
                key="D1",
                title="the canal morning",
                account="",
                significance="",
                role="supporting",
                uncertainty="",
                moments=["M1", "M2"],
            ),
            StoryEpisode(
                key="D2",
                title="the trip",
                account="",
                significance="",
                role="minor",
                uncertainty="",
                moments=["M3"],
            ),
        ],
        connections=[],
        priorities=[],
        uncertainties=[],
        audit={},
        stories=[
            {"key": "S1", "episodes": ["D1"], "weight": "major"},
            {"key": "S2", "episodes": ["D2"], "weight": "minor"},
        ],
    )
    return StorySelection(
        carriers=carriers,
        story=story,
        episodes=[
            {"episode": "S1", "day_episodes": ["D1"]},
            {"episode": "S2", "day_episodes": ["D2"]},
        ],
        alternatives_of=alternatives_of,
        slots=4,
        calls={},
        lines={
            "mate": "mate's own line",
            "spare": "spare's own line",
            "far": "far's own line",
            "other-story": "other-story's own line",
        },
        unfunded_pool=list(unfunded_pool),
    )


def unit(asset_id, moment, taken):
    return {"asset_id": asset_id, "moment": moment, "kind": "still", "taken": taken}


def pool_of(
    carriers,
    alternatives_of,
    event_units,
    anchor_label,
    unfunded_pool=(),
    *,
    include_elsewhere=False,
    partition_of=None,
):
    return alternatives_pool(
        selection(carriers, alternatives_of, unfunded_pool),
        event_units,
        anchor_label,
        include_elsewhere=include_elsewhere,
        partition_of=partition_of,
    )


def test_context_comes_from_the_pool_units_own_moment():
    refused = {
        "asset_id": "held",
        "event": "F01",
        "anchor": "A1",
        "chapter": 1,
        "why": "a Live Photo of the poetry book",
        "story_episode": "S1",
    }
    pool = pool_of(
        [refused],
        {"held": ["mate", "spare", "far"]},
        {
            "F01": [unit("held", "M1", "2024-06-01T09:00"), unit("mate", "M1", "2024-06-01T09:04")],
            "F02": [unit("spare", "M2", "2024-06-01T11:00")],
            "F03": [unit("far", "M3", "2024-06-03T11:00")],
        },
        {"F01": "A1", "F02": "A2", "F03": "A3"},
    )

    rows = {row["asset_id"]: row for row in pool(refused)}

    assert rows["mate"]["event"] == "F01" and rows["mate"]["anchor"] == "A1"
    assert rows["spare"]["event"] == "F02" and rows["spare"]["anchor"] == "A2"
    assert rows["far"]["event"] == "F03" and rows["far"]["anchor"] == "A3"
    # The far spare belongs to the second story: it takes that story's chapter, not the
    # refused carrier's, and its own line replaces a borrowed description.
    assert rows["far"]["chapter"] == 2 and rows["mate"]["chapter"] == 1
    assert rows["spare"]["line"] == "spare's own line"
    assert rows["far"]["story_episode"] == "S2"
    assert rows["far"]["story_weight"] == "minor"


def test_the_pool_reaches_another_storys_unfunded_moment_once_its_own_runs_out():
    """Nothing left in the carrier's own moment or story: the final review's widened pool,
    from a story that never got a slot, fills in, in that story's own context. The audience
    gate's own (narrower) pool never reaches this far; see
    `test_the_audience_gates_own_pool_never_reaches_elsewhere` below."""
    refused = {
        "asset_id": "held",
        "event": "F01",
        "why": "a picture",
        "story_episode": "S1",
        "taken": "2024-06-01T09:00",
    }
    pool = pool_of(
        [refused],
        {"held": []},  # the moment and the story both have nothing left
        {
            "F01": [unit("held", "M1", "2024-06-01T09:00")],
            "F03": [unit("other-story", "M3", "2024-06-03T11:00")],
        },
        {"F01": "A1", "F03": "A3"},
        unfunded_pool=["other-story"],
        include_elsewhere=True,
    )

    rows = pool(refused)

    assert [row["asset_id"] for row in rows] == ["other-story"]
    assert rows[0]["story_episode"] == "S2"
    assert rows[0]["line"] == "other-story's own line"


def test_the_audience_gates_own_pool_never_reaches_elsewhere():
    """The audience gate drops a carrier rather than widen its search past the carrier's own
    moment and story (`editorial_shareability.apply_gate`'s own contract): `include_elsewhere`
    defaults to off, which is what `apply_audience_gate` asks for."""
    refused = {
        "asset_id": "held",
        "event": "F01",
        "why": "a picture",
        "story_episode": "S1",
        "taken": "2024-06-01T09:00",
    }
    pool = pool_of(
        [refused],
        {"held": []},
        {
            "F01": [unit("held", "M1", "2024-06-01T09:00")],
            "F03": [unit("other-story", "M3", "2024-06-03T11:00")],
        },
        {"F01": "A1", "F03": "A3"},
        unfunded_pool=["other-story"],
    )

    assert pool(refused) == []


def test_elsewhere_never_offers_a_month_the_film_does_not_already_show():
    """The timing and partition budget are bound to the months selection settled on: an
    elsewhere offer from a month nothing else in the film shows is never made, so the film
    stays short of that slot rather than pull in a new month this late."""
    refused = {
        "asset_id": "held",
        "event": "F01",
        "why": "a picture",
        "story_episode": "S1",
        "taken": "2024-06-01T09:00",
    }
    other_carrier = {"asset_id": "other-carrier", "taken": "2024-06-15T09:00"}
    pool = pool_of(
        [refused, other_carrier],
        {"held": [], "other-carrier": []},
        {
            "F01": [unit("held", "M1", "2024-06-01T09:00")],
            "F03": [unit("other-story", "M3", "2024-07-03T11:00")],  # a month shown nowhere
        },
        {"F01": "A1", "F03": "A3"},
        unfunded_pool=["other-story"],
        include_elsewhere=True,
    )

    assert pool(refused) == []


def test_elsewhere_respects_the_products_partition_limit():
    """A product that caps carriers per partition never has elsewhere cross partitions: the
    same rule the carrier's own spares already had to meet (`editorial_story_carriers._spares`).
    Both offers are in the month the film already shows, so only the partition rule tells
    them apart."""
    refused = {
        "asset_id": "held",
        "event": "F01",
        "why": "a picture",
        "story_episode": "S1",
        "taken": "2024-06-01T09:00",
    }
    pool = pool_of(
        [refused],
        {"held": []},
        {
            "F01": [unit("held", "M1", "2024-06-01T09:00")],
            "F02": [unit("same-partition", "M2", "2024-06-01T15:00")],
            "F03": [unit("other-partition", "M3", "2024-06-15T11:00")],
        },
        {"F01": "A1", "F02": "A2", "F03": "A3"},
        unfunded_pool=["same-partition", "other-partition"],
        include_elsewhere=True,
        partition_of=lambda taken: taken[:10],  # one partition per day
    )

    assert [row["asset_id"] for row in pool(refused)] == ["same-partition"]


def test_a_pool_unit_never_carries_the_refused_carriers_why():
    refused = {"asset_id": "held", "event": "F01", "why": "a Live Photo of the poetry book"}
    pool = pool_of(
        [refused],
        {"held": ["mate"]},
        {"F01": [unit("held", "M1", "2024-06-01T09:00"), unit("mate", "M1", "2024-06-01T09:04")]},
        {"F01": "A1"},
    )

    rows = pool(refused)

    assert rows and all("poetry" not in str(row) for row in rows)
