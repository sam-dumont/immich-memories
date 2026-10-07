"""Run the season, holiday, album, backfill and per-person month detectors over one snapshot."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date

from immich_memories.automation.album_detector import AlbumDetector
from immich_memories.automation.backfill_detector import BackfillDetector
from immich_memories.automation.candidates import Detection, MemoryCandidate
from immich_memories.automation.discovery_extras import ExtraReads
from immich_memories.automation.person_detectors import PersonMonthlyDetector
from immich_memories.automation.season_holiday_detectors import HolidayDetector, SeasonDetector
from immich_memories.config_models_automation import AutomationConfig


def run_extra_detectors(
    auto_cfg: AutomationConfig,
    extras: ExtraReads,
    *,
    hemisphere: str | None,
    people: list,
    assets_by_month: dict[str, int],
    generated_keys: Collection[str],
    proposed: list[MemoryCandidate],
    today: date,
) -> Detection:
    """Every enabled detector's candidates, with the reasons the others proposed nothing.

    ``proposed`` are the other detectors' candidates: a month one of them already offered
    is not offered again as backfill.
    """
    found: list[Detection] = []
    if auto_cfg.detect_seasons:
        found.append(SeasonDetector().detect(today, hemisphere, generated_keys, extras.season_days))
    if auto_cfg.detect_holidays:
        found.append(
            HolidayDetector().detect(
                today,
                extras.country,
                auto_cfg.extra_holidays,
                generated_keys,
                extras.holiday_pictures,
            )
        )
    if auto_cfg.detect_albums:
        found.append(
            AlbumDetector().detect(
                extras.albums,
                extras.user_id,
                generated_keys,
                today,
                include_shared=auto_cfg.include_shared_albums,
            )
        )
    if auto_cfg.detect_person_monthly:
        found.append(
            PersonMonthlyDetector().detect(
                people, extras.close_ids, extras.person_days, generated_keys, today
            )
        )
    if auto_cfg.backfill_months:
        found.append(
            BackfillDetector().detect(
                assets_by_month, generated_keys, today, {c.memory_key for c in proposed}
            )
        )
    return Detection(
        [c for detection in found for c in detection.candidates],
        tuple(dict.fromkeys(n for detection in found for n in detection.notes)),
    )
