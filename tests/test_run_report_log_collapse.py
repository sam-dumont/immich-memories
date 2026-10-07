"""A pasted run report keeps one line per progress stage and one per repeated message (#2127)."""

from datetime import UTC, datetime

from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.report import build_report
from immich_memories.tracking.report_privacy import ReportPrivacy
from immich_memories.tracking.timing import Collector


def _pasted_logs(lines: list[str]) -> list[str]:
    report = build_report(
        RunMetadata("collapse-run", datetime.now(UTC)),
        Collector(logs=lines),
        privacy=ReportPrivacy(),
    )
    markdown = report.markdown()
    block = markdown.split("<summary>Run logs (redacted)</summary>", 1)[1]
    return block.split("<pre>", 1)[1].split("</pre>", 1)[0].splitlines()


def test_a_stage_keeps_only_its_final_progress_count():
    lines = [
        "Preparing previews: 1/39",
        "Preparing previews: 33/39 · ~1s left in this stage",
        "Preparing previews: 39/39",
        "Preparing pixels: 1/39",
        "Preparing pixels: 39/39",
    ]

    shown = _pasted_logs(lines)

    assert "Preparing previews: 39/39" in shown
    assert "Preparing pixels: 39/39" in shown
    assert not any("1/39" in line or "33/39" in line for line in shown)


def test_a_later_stage_with_the_same_name_and_another_total_is_its_own_stage():
    lines = ["Preparing previews: 39/39", "Preparing previews: 1/7", "Preparing previews: 7/7"]

    shown = _pasted_logs(lines)

    assert "Preparing previews: 39/39" in shown
    assert "Preparing previews: 7/7" in shown
    assert "Preparing previews: 1/7" not in shown


def test_a_repeated_line_is_shown_once_with_its_count():
    burst = "Burst de-duplication: 5 of 28 photos dropped as near-identical frames within 300s"
    lines = [burst, burst, "Editing the memory", burst, burst]

    shown = _pasted_logs(lines)

    assert sum(burst in line for line in shown) == 1
    assert f"{burst} (x4)" in shown


def test_the_json_and_the_bundle_log_stay_whole():
    lines = ["Preparing previews: 1/3", "Preparing previews: 3/3", "same", "same"]
    report = build_report(
        RunMetadata("whole-run", datetime.now(UTC)),
        Collector(logs=lines),
        privacy=ReportPrivacy(),
    )

    assert report.data["logs"] == lines
