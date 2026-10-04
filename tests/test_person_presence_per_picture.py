"""From the fetch to the cut, a people condition is strict per picture (#1954).

A missed face (the back of a head, a baby feeding against a chest, a child across the
garden) costs that picture rather than loosening the rule: bundling in a picture with the
wrong people is worse than losing a good one. The fetch decides this once, over the
window Immich returns; the pool the owner reviews and the cut both use that one answer.
"""

from dataclasses import replace
from datetime import timedelta

import sqlalchemy as sa

from immich_memories.analysis.editorial_planner import EditorialPlan
from immich_memories.analysis.editorial_preparation import prepare_editorial_annotations
from immich_memories.analysis.editorial_runtime import EditorialRunContext, build_editorial_planner
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.selection_trace import Trace
from immich_memories.api.models import Person
from immich_memories.api.person_expression import PersonExpression
from immich_memories.api.person_scope import people_in_window, window_condition
from immich_memories.config_loader import Config
from immich_memories.db.tables.annotations import head_facts
from tests.test_editorial_preparation import preview, successful_ports
from tests.test_editorial_runtime import _window
from tests.test_editorial_source_route import photo

WINDOW = _window(2020, 5, 2)


def shot(key, *, hour, minute=0, people=()):
    asset = photo(key, at=WINDOW.start + timedelta(hours=hour, minutes=minute))
    asset.people = [Person(id=f"face-{name.lower()}", name=name) for name in people]
    return asset


class _Library:
    """WHY: Immich is the read boundary; the window holds these pictures and nothing else."""

    def __init__(self, window):
        self.window = window

    def get_videos_for_date_range(self, _window):
        return []

    def get_photos_for_date_range(self, _window):
        return list(self.window)


def _face(name: str) -> str:
    return f"face-{name.lower()}"


def fetched_pool(window, *, people=(), person_match="and", person_expression=None):
    """The pool the fetch hands the cut: the same call the CLI and the wizard make."""
    condition = window_condition(
        [_face(name) for name in people] if person_expression is None else [],
        person_match=person_match,
        person_expression=person_expression.map_leaves(_face) if person_expression else None,
    )
    if condition is None:
        return list(window)
    _videos, photos = people_in_window(_Library(window), WINDOW, condition)
    return photos


def selectable(tmp_path, monkeypatch, *, window, fetched=None, providers=None, **context):
    """The pictures the editor may choose from, after the fetch and the cut."""
    config = Config(
        llm={"enabled": True, "model": "offline-editor"},
        cache={"directory": str(tmp_path / "cache")},
        analysis={"min_source_short_side": 0},
        editorial={"preparation": {"tier": "full"}},
    )
    planner = build_editorial_planner(
        client=object(),
        config=config,
        thumbnail_cache=tmp_path / "previews",
        context=EditorialRunContext(
            "people", "People", "person_spotlight", (WINDOW,), 60, tmp_path / "runs", **context
        ),
        ports=EditorialRuntimePorts(
            load_people=lambda: {},
            fetch_full_source=lambda _client, _scope: window,
            fetch_preview=lambda _client, _asset_id: preview(),
            fetch_faces=lambda _client, _asset_id: (),
            prepare_annotations=lambda **kwargs: prepare_editorial_annotations(
                **kwargs, ports=providers or successful_ports([])
            ),
        ),
    )
    seen: list[str] = []

    def editor(candidates, **_):
        seen.extend(row.clip.asset.id for row in candidates)
        return EditorialPlan()

    # WHY: the editor is the next stage's boundary; this test is about the pool it is handed.
    monkeypatch.setattr(planner._planner, "plan_prepared", editor)
    pool = fetched_pool(window, **context) if fetched is None else fetched
    planner.plan_source(pool, trace=Trace())
    return set(seen)


def test_the_cut_keeps_only_the_exact_picture_the_person_is_recognised_on(tmp_path, monkeypatch):
    face = shot("face", hour=9, people=("Ada",))
    back_of_head = shot("back-of-head", hour=9, minute=20)
    elsewhere = shot("afternoon", hour=15)

    pool = selectable(
        tmp_path, monkeypatch, window=[face, back_of_head, elsewhere], people=("Ada",)
    )

    assert pool == {"face"}


def test_and_needs_everyone_on_the_same_picture_not_just_the_same_afternoon(tmp_path, monkeypatch):
    ada_alone = shot("ada-alone", hour=9, people=("Ada",))
    ben_alone = shot("ben-alone", hour=9, minute=30, people=("Ben",))
    both = shot("both", hour=9, minute=45, people=("Ada", "Ben"))
    nobody_recognised = shot("nobody-recognised", hour=15)

    pool = selectable(
        tmp_path,
        monkeypatch,
        window=[ada_alone, ben_alone, both, nobody_recognised],
        people=("Ada", "Ben"),
        person_match="and",
    )

    assert pool == {"both"}


def test_a_grouped_condition_is_read_per_picture_too(tmp_path, monkeypatch):
    window = [
        shot("ada-morning", hour=9, people=("Ada",)),
        shot("ben-morning", hour=9, minute=30, people=("Ben",)),
        shot("ada-and-ben", hour=9, minute=45, people=("Ada", "Ben")),
        shot("cy-afternoon", hour=15, people=("Cy",)),
        shot("afternoon-unrecognised", hour=15, minute=10),
    ]

    pool = selectable(
        tmp_path,
        monkeypatch,
        window=window,
        person_expression=PersonExpression.parse('("Ada" AND "Ben") OR "Cy"'),
    )

    assert pool == {"ada-and-ben", "cy-afternoon"}


def test_a_film_about_nobody_keeps_the_pictures_it_asked_for(tmp_path, monkeypatch):
    asked = shot("asked", hour=9, people=("Ada",))
    neighbour = shot("neighbour", hour=9, minute=20)

    pool = selectable(tmp_path, monkeypatch, window=[asked, neighbour], fetched=[asked])

    assert pool == {"asked"}


def test_an_exclusion_of_one_picture_never_touches_a_different_picture_s_people_match(
    tmp_path, monkeypatch
):
    """The owner saw an unrelated screen photo refused; that must not cost a real match."""
    face = shot("face", hour=9, people=("Ada",))
    bridge = shot("screen", hour=10, minute=20, people=("Ada",))
    later = shot("later", hour=11, minute=40, people=("Ada",))
    providers = successful_ports([])

    def heads(**kwargs):
        providers.heads(**kwargs)
        with kwargs["store"].begin() as connection:
            connection.execute(
                sa.update(head_facts)
                .where(head_facts.c.asset_id == "screen", head_facts.c.head == "screen")
                .values(label="yes")
            )

    pool = selectable(
        tmp_path,
        monkeypatch,
        window=[face, bridge, later],
        people=("Ada",),
        providers=replace(providers, heads=heads),
    )

    assert pool == {"face", "later"}
