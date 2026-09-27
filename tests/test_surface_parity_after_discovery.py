"""Auto duration after discovery: the length a film runs is fitted to the pool it found.

``test_surface_parity.py`` covers what the CLI asks for before it has seen a single
picture. The length a film actually runs is decided later, from the material discovery
found (#1087, #1094). The web client runs the CLI itself, so this is the one surface.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from immich_memories.api.models import Asset, AssetType, VideoClipInfo
from immich_memories.cli._pipeline_runner import _decide_duration
from immich_memories.config import Config
from immich_memories.memory_types.registry import MemoryType
from immich_memories.planning.auto_duration import (
    DURATION_FROM_DURATION_FLAG,
    DURATION_FROM_MATERIAL,
)
from tests.test_surface_parity import SPECS, cli_duration


def _asset(asset_id: str, when: datetime, asset_type: AssetType) -> Asset:
    return Asset(
        id=asset_id,
        type=asset_type,
        fileCreatedAt=when,
        fileModifiedAt=when,
        updatedAt=when,
    )


def _clip(asset_id: str, when: datetime) -> VideoClipInfo:
    return VideoClipInfo(
        asset=_asset(asset_id, when, AssetType.VIDEO),
        duration_seconds=12.0,
        width=1920,
        height=1080,
    )


def _pool(
    first_day: datetime, days: int, *, clips_a_day: int, photos_a_day: int
) -> tuple[list[VideoClipInfo], list[Asset]]:
    clips: list[VideoClipInfo] = []
    photos: list[Asset] = []
    for day in range(days):
        when = first_day + timedelta(days=day, hours=12)
        clips.extend(_clip(f"v-{day}-{index}", when) for index in range(clips_a_day))
        photos.extend(
            _asset(f"p-{day}-{index}", when, AssetType.IMAGE) for index in range(photos_a_day)
        )
    return clips, photos


MARCH = datetime(2024, 3, 1, tzinfo=UTC)
# Every day of March photographed: far more than a one-minute film can hold.
DENSE_MONTH = _pool(MARCH, 31, clips_a_day=2, photos_a_day=6)
# Three stills on three days: nowhere near a minute of varied footage.
THIN_MONTH = _pool(MARCH, 3, clips_a_day=0, photos_a_day=1)


def cli_auto_seconds(
    memory_type: MemoryType,
    pool: tuple[list[VideoClipInfo], list[Asset]],
    *,
    config: Config,
    duration: float | None = None,
) -> float:
    """The length ``run_pipeline_and_generate`` settles on for this pool."""
    clips, photos = pool
    decision = _decide_duration(
        duration,
        requested_source=DURATION_FROM_DURATION_FLAG
        if duration is not None
        else DURATION_FROM_MATERIAL,
        preset_duration=cli_duration(memory_type, SPECS[memory_type]),
        memory_type=str(memory_type),
        clips=clips,
        photos=photos,
        config=config,
    )
    return decision.seconds


class TestAutoDurationAfterDiscovery:
    def test_a_thin_month_is_shortened(self) -> None:
        """A card's minute is not kept for a pool that cannot fill it."""
        assert cli_auto_seconds(MemoryType.MONTHLY_HIGHLIGHTS, THIN_MONTH, config=Config()) < 60.0

    def test_an_explicit_target_wins(self) -> None:
        """``--duration`` is the owner's ask: the pool does not move it."""
        cli = cli_auto_seconds(
            MemoryType.MONTHLY_HIGHLIGHTS, THIN_MONTH, config=Config(), duration=150.0
        )

        assert cli == 150.0

    def test_a_fuller_pool_gets_a_longer_film(self) -> None:
        config = Config()

        thin = cli_auto_seconds(MemoryType.MONTHLY_HIGHLIGHTS, THIN_MONTH, config=config)
        dense = cli_auto_seconds(MemoryType.MONTHLY_HIGHLIGHTS, DENSE_MONTH, config=config)

        assert dense > thin
