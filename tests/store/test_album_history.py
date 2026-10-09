"""Album discovery reads the keys written by real manual and scheduled run history."""

from datetime import UTC, date, datetime

import pytest

from immich_memories.automation.album_detector import AlbumDetector
from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams, build_memory_key
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase

_ALBUM = {
    "id": "album-one",
    "albumName": "Test album",
    "assetCount": 40,
    "startDate": "2025-05-01T09:00:00Z",
    "endDate": "2025-05-05T18:00:00Z",
}
_TODAY = date(2026, 1, 1)


@pytest.mark.parametrize(
    ("first", "last"),
    [
        (datetime(2025, 5, 1), datetime(2025, 5, 5, 23, 59, 59)),
        (datetime(2025, 5, 1, 9), datetime(2025, 5, 5, 18)),
        (datetime(2025, 5, 1, 9, tzinfo=UTC), datetime(2025, 5, 5, 18, tzinfo=UTC)),
    ],
)
def test_manual_album_film_is_not_proposed_again(store, tmp_path, first, last):
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "album.mp4",
        config=Config(),
        memory_type="album",
        date_start=first,
        date_end=last,
    )
    history = RunDatabase(store)
    history.save_run(
        RunMetadata(
            run_id="manual-album",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            status="completed",
            output_path=str(params.output_path),
            memory_key=build_memory_key(params),
            memory_type="album",
            source="manual",
        )
    )

    detection = AlbumDetector().detect(
        [_ALBUM],
        None,
        history.get_generated_memory_keys(),
        _TODAY,
        include_shared=False,
    )

    assert detection.candidates == []
    assert any("already have hand-made films" in note for note in detection.notes)


def test_scheduled_album_film_only_returns_after_enough_growth(store, tmp_path):
    detector = AlbumDetector()
    (candidate,) = detector.detect([_ALBUM], None, set(), _TODAY, include_shared=False).candidates
    history = RunDatabase(store)
    history.save_run(
        RunMetadata(
            run_id="scheduled-album",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            status="completed",
            output_path=str(tmp_path / "album.mp4"),
            memory_key=candidate.memory_key,
            memory_type="album",
            source="auto",
        )
    )
    keys = history.get_generated_memory_keys()

    assert detector.detect([_ALBUM], None, keys, _TODAY, include_shared=False).candidates == []
    grown = detector.detect([_ALBUM | {"assetCount": 70}], None, keys, _TODAY, include_shared=False)
    assert len(grown.candidates) == 1
    assert grown.candidates[0].memory_key != candidate.memory_key
