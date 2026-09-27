"""A person film counts someone present wherever their face is recognised in the episode.

Faces go unrecognised for people who are really there: the back of a head, a baby
feeding against a chest, a child across the garden. Immich's person query answers
per frame, so a person film used to lose every one of those pictures. The pool is
the episode now: one recognised face puts the person in every picture of the same
90-minute episode, and no further.
"""

from datetime import timedelta

from immich_memories.analysis.editorial_planner import EditorialPlan
from immich_memories.analysis.editorial_preparation import prepare_editorial_annotations
from immich_memories.analysis.editorial_runtime import EditorialRunContext, build_editorial_planner
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.selection_trace import Trace
from immich_memories.api.models import Person
from immich_memories.api.person_expression import PersonExpression
from immich_memories.config_loader import Config
from tests.test_editorial_preparation import preview, successful_ports
from tests.test_editorial_runtime import _window
from tests.test_editorial_source_route import photo

WINDOW = _window(2020, 5, 2)


def shot(key, *, hour, minute=0, people=()):
    asset = photo(key, at=WINDOW.start + timedelta(hours=hour, minutes=minute))
    asset.people = [Person(id=f"face-{name.lower()}", name=name) for name in people]
    return asset


def selectable(tmp_path, monkeypatch, *, window, fetched, **context):
    """The pictures the editor may choose from, given what Immich's face query returned."""
    config = Config(
        llm={"model": "offline-editor"},
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
                **kwargs, ports=successful_ports([])
            ),
        ),
    )
    seen: list[str] = []

    def editor(candidates, **_):
        seen.extend(row.clip.asset.id for row in candidates)
        return EditorialPlan()

    # WHY: the editor is the next stage's boundary; this test is about the pool it is handed.
    monkeypatch.setattr(planner._planner, "plan_prepared", editor)
    planner.plan_source(fetched, trace=Trace())
    return set(seen)


def test_one_recognised_face_puts_the_person_in_every_picture_of_that_episode(
    tmp_path, monkeypatch
):
    face = shot("face", hour=9, people=("Ada",))
    back_of_head = shot("back-of-head", hour=9, minute=20)
    elsewhere = shot("afternoon", hour=15)

    pool = selectable(
        tmp_path,
        monkeypatch,
        window=[face, back_of_head, elsewhere],
        fetched=[face],
        people=("Ada",),
    )

    assert pool == {"face", "back-of-head"}


def test_and_asks_for_everyone_somewhere_in_the_episode_not_in_one_frame(tmp_path, monkeypatch):
    morning = [
        shot("ada-alone", hour=9, people=("Ada",)),
        shot("ben-alone", hour=9, minute=30, people=("Ben",)),
        shot("nobody-recognised", hour=9, minute=45),
    ]
    only_ada_later = [
        shot("ada-afternoon", hour=15, people=("Ada",)),
        shot("afternoon-unrecognised", hour=15, minute=10),
    ]

    pool = selectable(
        tmp_path,
        monkeypatch,
        window=[*morning, *only_ada_later],
        fetched=[],
        people=("Ada", "Ben"),
        person_match="and",
    )

    assert pool == {"ada-alone", "ben-alone", "nobody-recognised"}


def test_a_grouped_condition_is_read_per_episode_too(tmp_path, monkeypatch):
    window = [
        shot("ada-morning", hour=9, people=("Ada",)),
        shot("ben-morning", hour=9, minute=30, people=("Ben",)),
        shot("cy-afternoon", hour=15, people=("Cy",)),
        shot("afternoon-unrecognised", hour=15, minute=10),
        shot("ada-evening", hour=20, people=("Ada",)),
    ]

    pool = selectable(
        tmp_path,
        monkeypatch,
        window=window,
        fetched=[],
        person_expression=PersonExpression.parse('("Ada" AND "Ben") OR "Cy"'),
    )

    assert pool == {"ada-morning", "ben-morning", "cy-afternoon", "afternoon-unrecognised"}


def test_a_film_about_nobody_keeps_the_pictures_it_asked_for(tmp_path, monkeypatch):
    asked = shot("asked", hour=9, people=("Ada",))
    neighbour = shot("neighbour", hour=9, minute=20)

    pool = selectable(tmp_path, monkeypatch, window=[asked, neighbour], fetched=[asked])

    assert pool == {"asked"}
