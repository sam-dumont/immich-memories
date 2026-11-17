"""Duration, length and music warnings are stored as codes and worded in the film's language.

They were stored as English text, so a French completion notice and run page showed them
in English (#2665). English must still read exactly as the old text did.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from immich_memories.analysis.runtime.duration_advisory import editorial_duration_warning
from immich_memories.audio.generators.ace_step_model_choice import HostMemory
from immich_memories.audio.generators.ace_step_music_path import decide_music_path
from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_music import optional_music_warning, resolve_music
from immich_memories.generate_timeline import validate_final_duration
from immich_memories.operational_warnings import JOINER, render_warning, scrub_warning
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.remote_render import check_film_length
from tests.conftest import make_clip

SHORTFALL = {
    "requested_seconds": 40.5,
    "content_budget_seconds": 33.1,
    "selected_content_seconds": 4.5,
    "status": "editorial_shortfall",
}


def _clips(count: int) -> list[AssemblyClip]:
    return [AssemblyClip(Path(), 4.0, asset_id=f"clip-{index}") for index in range(count)]


def _budget_params(tmp_path: Path, target: float) -> GenerationParams:
    return GenerationParams(
        clips=[make_clip("clip-1")],
        output_path=tmp_path / "memory.mp4",
        config=Config(),
        target_duration_seconds=target,
    )


def test_a_short_selection_reads_in_english_as_it_did_and_in_french() -> None:
    stored = editorial_duration_warning(SHORTFALL)

    assert stored is not None and stored.startswith("warn.")
    assert render_warning(stored) == (
        "Selected 4.5s of pictures and video for a 40.5s memory "
        "(33.1s available for content). More usable material may remain."
    )
    assert render_warning(stored, "fr") == (
        "4.5 s de photos et de vidéos retenues pour un film de 40.5 s "
        "(33.1 s disponibles pour le contenu). Il reste peut-être d'autres images utilisables."
    )


def test_a_selection_that_stopped_early_keeps_its_cause_in_both_languages() -> None:
    stored = editorial_duration_warning(SHORTFALL | {"status": "search_limited"})

    assert stored is not None
    assert render_warning(stored) == (
        "Selection stopped early. Selected 4.5s of pictures and video for a 40.5s memory "
        "(33.1s available for content). More usable material may remain."
    )
    assert render_warning(stored, "fr").startswith(
        "Sélection arrêtée avant la fin. 4.5 s de photos et de vidéos retenues"
    )


def test_a_film_over_its_budget_reads_in_english_as_it_did_and_in_french(tmp_path) -> None:
    stored = validate_final_duration(_budget_params(tmp_path, 100.0), 103.0)

    assert stored is not None
    assert render_warning(stored) == "Final artifact ran 103.0s against a 100.0s budget (3.0s over)"
    assert render_warning(stored, "fr") == (
        "Le film final dure 103.0 s pour un budget de 100.0 s (3.0 s de trop)"
    )


@pytest.mark.parametrize(
    ("actual", "english", "french"),
    [
        (
            589.133,
            "The render worker's film runs 589.1s against the 604.0s planned (-14.9s)",
            "Le film du worker de rendu dure 589.1 s pour 604.0 s prévues (-14.9 s)",
        ),
        (
            618.0,
            "The render worker's film runs 618.0s against the 604.0s planned (+14.0s)",
            "Le film du worker de rendu dure 618.0 s pour 604.0 s prévues (+14.0 s)",
        ),
    ],
)
def test_a_worker_film_off_its_plan_reads_in_both_languages(
    actual: float, english: str, french: str
) -> None:
    stored = check_film_length(actual, 603.984, _clips(150))

    assert stored is not None
    assert render_warning(stored) == english
    assert render_warning(stored, "fr") == french


def test_a_music_failure_words_its_frame_and_keeps_the_error_as_it_is() -> None:
    stored = optional_music_warning(RuntimeError("backend unavailable"))

    assert render_warning(stored) == "Optional music failed: backend unavailable"
    assert render_warning(stored, "fr") == ("Échec de la musique facultative : backend unavailable")


def test_a_music_failure_still_hides_a_configured_secret() -> None:
    config = Config()
    config.musicgen.api_key = "top-secret-917"

    stored = optional_music_warning(RuntimeError("rejected top-secret-917 at /x?a=b"), config)

    assert "top-secret-917" not in stored
    assert render_warning(stored) == "Optional music failed: rejected *** at /x?a=b"
    rescrubbed = scrub_warning(stored, lambda text: text.replace("/x?a=b", "***"))
    assert render_warning(rescrubbed) == "Optional music failed: rejected *** at ***"


def _library(tmp_path: Path) -> Path:
    folder = tmp_path / "library" / "happy"
    folder.mkdir(parents=True)
    (folder / "track.mp3").write_bytes(b"not really an mp3")
    return tmp_path / "library"


def _failed_generator_music(tmp_path: Path, monkeypatch, library: Path | None):
    def unreachable(*_args: object, **_kwargs: object) -> Path:
        raise ConnectionError("All connection attempts failed")

    # WHY: stands in for the music backend, unreachable as on a fresh enable.
    monkeypatch.setattr("immich_memories.generate_music.auto_generate_music", unreachable)
    config = Config()
    config.musicgen.enabled = True
    return resolve_music(
        config,
        None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path,
        memory_type=None,
        bundled_library=library,
        transition_overlap=0.0,
    )


def test_the_bundled_track_fallback_is_worded_with_the_failure(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)

    selection = _failed_generator_music(tmp_path, monkeypatch, _library(tmp_path))

    english = "Optional music failed: All connection attempts failed; used a bundled track instead"
    assert selection.warning is not None
    assert render_warning(selection.warning) == english
    assert render_warning(selection.warning, "fr") == (
        "Échec de la musique facultative : All connection attempts failed; "
        "un morceau intégré a été utilisé à la place"
    )
    # The log is read by people and by the feature matrix: it carries the English words.
    assert english in caplog.text
    assert "warn." not in caplog.text


def test_no_track_to_fall_back_on_is_worded_too(tmp_path, monkeypatch) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    selection = _failed_generator_music(tmp_path, monkeypatch, empty)

    assert selection.path is None and selection.warning is not None
    assert render_warning(selection.warning) == (
        "Optional music failed: All connection attempts failed; "
        "no bundled track available; no music added"
    )
    assert render_warning(selection.warning, "fr").endswith(
        "aucun morceau intégré disponible ; aucune musique ajoutée"
    )


@pytest.mark.parametrize(
    ("host", "english", "french"),
    [
        (
            HostMemory(unified_gib=32.0),
            "this host has 32 GB of unified memory; the XL model needs 64 GB of unified "
            "memory or a 16 GB GPU, so the bundled library plays",
            "cette machine a 32 Go de mémoire unifiée ; le modèle XL demande 64 Go de "
            "mémoire unifiée ou un GPU de 16 Go, donc la bibliothèque intégrée est utilisée",
        ),
        (
            HostMemory(gpu_gib=8.0),
            "this host has a 8 GB GPU; the XL model needs 64 GB of unified memory or a "
            "16 GB GPU, so the bundled library plays",
            "cette machine a un GPU de 8 Go ; le modèle XL demande 64 Go de mémoire "
            "unifiée ou un GPU de 16 Go, donc la bibliothèque intégrée est utilisée",
        ),
        (
            HostMemory(),
            "this host has no GPU or unified memory it can use; the XL model needs 64 GB "
            "of unified memory or a 16 GB GPU, so the bundled library plays",
            "cette machine n'a ni GPU ni mémoire unifiée utilisable ; le modèle XL demande "
            "64 Go de mémoire unifiée ou un GPU de 16 Go, donc la bibliothèque intégrée est utilisée",
        ),
    ],
)
def test_why_a_host_plays_the_bundled_library_in_both_languages(
    host: HostMemory, english: str, french: str
) -> None:
    path = decide_music_path(mode="lib", configured="auto", host=host, server_model=None)

    assert not path.generate
    assert render_warning(path.reason) == english
    assert render_warning(path.reason, "fr") == french


@pytest.mark.parametrize(
    ("server_model", "english"),
    [
        (
            None,
            "could not learn which model the ACE-Step server runs (unreachable, or no "
            "loaded_model on /health), so the bundled library plays; set model_variant to "
            "'xl-turbo' if it runs XL",
        ),
        (
            "acestep-v15-turbo",
            "the ACE-Step server runs acestep-v15-turbo, not an XL model; the bundled library plays",
        ),
    ],
)
def test_why_a_server_plays_the_bundled_library_reads_as_it_did(
    server_model: str | None, english: str
) -> None:
    path = decide_music_path(
        mode="api", configured="auto", host=HostMemory(), server_model=server_model
    )

    assert render_warning(path.reason) == english
    assert "ACE-Step" in render_warning(path.reason, "fr")
    assert render_warning(path.reason, "fr") != english


def test_skipped_generation_is_worded_with_its_reason(tmp_path, monkeypatch) -> None:
    from immich_memories.audio.generators import ace_step_music_path

    # WHY: a Mac with 32 GB, below the XL bar, running ACE-Step in its own environment.
    monkeypatch.setattr(ace_step_music_path, "measure_host", lambda: HostMemory(unified_gib=32.0))
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python", lambda: tmp_path
    )
    config = Config(ace_step={"enabled": True, "mode": "lib"})

    selection = resolve_music(
        config,
        None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path,
        memory_type=None,
        bundled_library=_library(tmp_path),
        transition_overlap=0.0,
    )

    assert selection.warning is not None
    assert render_warning(selection.warning) == (
        "Generated music skipped: this host has 32 GB of unified memory; the XL model needs "
        "64 GB of unified memory or a 16 GB GPU, so the bundled library plays; "
        "used a bundled track instead"
    )
    assert render_warning(selection.warning, "fr").startswith(
        "Musique générée non utilisée : cette machine a 32 Go de mémoire unifiée"
    )
    assert render_warning(selection.warning, "fr").endswith(
        "un morceau intégré a été utilisé à la place"
    )


def test_a_stored_warning_carries_no_join_inside_one_piece() -> None:
    """Each warning a run stores stays one piece per code, so joined reasons split back right."""
    stored = optional_music_warning(RuntimeError("a; b"))

    assert len(stored.split(JOINER)) == 1
    assert render_warning(stored) == "Optional music failed: a; b"


def test_a_log_line_that_words_a_stored_warning_is_not_kept_twice() -> None:
    """A run keeps its log warnings too; the English log line of a coded warning is the same one."""
    from immich_memories.operational_warnings import coded, merged_warnings

    music = optional_music_warning(RuntimeError("down")) + JOINER + coded("music_used_bundled")
    worker = check_film_length(589.133, 603.984, _clips(150)) or ""
    stored = [music, worker + JOINER + coded("film_over_budget", actual=1, budget=1, over=0)]
    logged = [
        "Optional music failed: down; used a bundled track instead",
        render_warning(worker),
        "A clip leaves the film",
        "A clip leaves the film",
    ]

    assert merged_warnings(stored, logged) == [*stored, "A clip leaves the film"]
