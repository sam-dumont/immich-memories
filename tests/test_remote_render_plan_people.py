"""A film of several people rendered on the worker frames every one of them (#2440).

The render request carried only `person_name`, the first person, so a remote
render of a two-person film panned to one of them and ignored the other.
"""

from __future__ import annotations

from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.processing.remote_render_plan import build_render_request
from tests.conftest import make_clip


def _request(tmp_path, **memory) -> dict:
    params = GenerationParams(
        clips=[make_clip("test-clip-001", duration=5.0)],
        output_path=tmp_path / "memory.mp4",
        config=Config(),
        **memory,
    )
    return build_render_request(params)["memory"]


def test_every_person_the_film_is_about_travels_to_the_worker(tmp_path):
    memory = _request(tmp_path, person_name="Kid", memory_people=("kid", "dad"))

    assert memory["person_name"] == "Kid"
    assert memory["memory_people"] == ["kid", "dad"]


def test_a_film_about_nobody_sends_no_people(tmp_path):
    assert _request(tmp_path)["memory_people"] == []
