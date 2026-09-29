"""The CLI and web client share this allowlisted report, with no sending side effect."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from immich_memories import __version__
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.report_privacy import ReportPrivacy
from immich_memories.tracking.timing import Collector

_METRICS = (
    "calls",
    "unmetered_calls",
    "prompt_tokens",
    "cached_prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "truncated",
    "cache_hits",
    "wall_seconds",
)


def _numbers(record: dict, keys: tuple[str, ...]) -> dict:
    return {
        key: record[key]
        for key in keys
        if isinstance(record.get(key), (int, float)) and not isinstance(record[key], bool)
    }


def _usage(record: dict) -> dict:
    result = _numbers(record, _METRICS)
    seconds, calls = result.get("wall_seconds", 0), result.get("calls", 0)
    hits = result.get("cache_hits", 0)
    result["seconds_per_call"] = seconds / calls if calls else None
    result["tokens_per_second"] = result.get("completion_tokens", 0) / seconds if seconds else None
    result["cache_hit_rate"] = hits / (calls + hits) if calls + hits else None
    for group in ("by_model", "by_stage"):
        result[group] = {name: _usage(spend) for name, spend in record.get(group, {}).items()}
    return result


def _details(title: str, content: str) -> str:
    return (
        f"<details>\n<summary>{title}</summary>\n\n<pre>{html.escape(content)}</pre>\n</details>\n"
    )


_PEAKS = ("peak_rss_mb", "peak_tree_rss_mb")


def _higher(held: float | None, seen: float | None) -> float | None:
    return seen if held is None else held if seen is None else max(held, seen)


def _megabytes(size: int | None) -> float | None:
    return None if size is None else size / 2**20


def _phase_table(rows: list[dict]) -> str:
    lines = [
        "| Phase | Seconds | Items | s/item | s/output second | Peak MB | With children MB |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        name = html.escape(row["name"]).replace("|", "&#124;").replace("\n", " ")
        numbers = [
            row.get(key)
            for key in ("seconds", "items", "seconds_per_item", "seconds_per_output_second")
        ]
        cells = [
            "n/a" if value is None else str(value) if index == 1 else f"{value:.3f}"
            for index, value in enumerate(numbers)
        ] + ["n/a" if row.get(key) is None else f"{row[key]:.0f}" for key in _PEAKS]
        line = "| " + " | ".join([name, *cells]) + " |"
        if sum(map(len, lines)) + len(line) > 5500:
            lines.append("\nMore phases in report.json in the bundle.")
            break
        lines.append(line)
    return "\n".join(lines) + "\n"


def _phase_totals(spans: list[dict], output_seconds: float) -> list[dict]:
    totals: dict[str, dict] = {}
    for span in spans:
        name = span["name"]
        if name == "run" or name.startswith("stage."):
            continue
        row = totals.setdefault(
            name, {"name": name, "seconds": 0.0, "items": 0} | dict.fromkeys(_PEAKS)
        )
        row["seconds"] += span["seconds"]
        row["items"] = (
            row["items"] + span["items"]
            if row["items"] is not None and span["items"] is not None
            else None
        )
        # Repeated spans sum their seconds, but memory is a high-water mark: keep the highest.
        row.update({key: _higher(row[key], span.get(key)) for key in _PEAKS})
    for row in totals.values():
        row["seconds_per_item"] = row["seconds"] / row["items"] if row["items"] else None
        row["seconds_per_output_second"] = (
            row["seconds"] / output_seconds if output_seconds else None
        )
    return list(totals.values())


@dataclass(frozen=True)
class RunReport:
    data: dict[str, Any]

    def json(self) -> str:
        """Full redacted data; no arbitrary run/config serialization."""
        return json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"

    def markdown(self, *, limit: int = 59_000) -> str:
        """Keep complete folding blocks and whole trailing log lines below the issue limit."""
        data = {key: value for key, value in self.data.items() if key not in {"logs", "phases"}}
        sections = []
        section_limit = min(3500, max(200, (limit - 7000) // max(1, len(data))))
        for key, value in data.items():
            text = json.dumps(value, ensure_ascii=False, indent=2)
            if len(_details(key, text)) > section_limit:
                text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if len(_details(key, text)) > section_limit:
                text = "Section too long for the pasted report; see report.json in the bundle."
            sections.append(_details(key.replace("_", " ").title(), text))
        table = _phase_table(self.data["phases"])
        prefix = (
            "## Immich Memories run report\n\nRepeated spans are summed; nested phases overlap.\n\n"
            + table
            + "\n"
            + "\n".join(sections)
        )
        lines = self.data["logs"]
        kept: list[str] = []
        budget = max(0, limit - len(prefix) - 300)
        for line in reversed(lines):
            cost = len(html.escape(line)) + 1
            if cost > budget:
                break
            kept.append(line)
            budget -= cost
        note = (
            f"Logs trimmed to the last {len(kept)} of {len(lines)} lines. Full logs in the bundle.\n"
            if len(kept) < len(lines)
            else ""
        )
        return prefix + "\n" + note + _details("Run logs (redacted)", "\n".join(reversed(kept)))

    def bundle(self) -> bytes:
        """A ZIP contains only the redacted report and logs; never pictures or raw files."""
        output = BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("report.md", self.markdown())
            archive.writestr("report.json", self.json())
            archive.writestr("run.log", "\n".join(self.data["logs"]))
        if output.tell() > 25_000_000:
            raise ValueError("Report bundle exceeds 25 MB")
        return output.getvalue()


def build_report(
    run: RunMetadata,
    collected: Collector,
    *,
    privacy: ReportPrivacy,
    diagnostics: dict | None = None,
    include_flagged_captions: bool = False,
) -> RunReport:
    """Choose diagnostic fields first, then redact every selected string."""
    diagnostics = diagnostics or {}
    privacy.include(ids=[run.run_id])
    spans = [
        {
            "id": measured.span_id,
            "parent": measured.parent_id,
            "name": measured.name,
            "seconds": measured.duration,
            "items": measured.items,
            "seconds_per_item": measured.duration / measured.items if measured.items else None,
            "seconds_per_output_second": measured.duration / run.output_duration_seconds
            if run.output_duration_seconds
            else None,
            "peak_rss_mb": _megabytes(measured.peak_rss),
            "peak_tree_rss_mb": _megabytes(measured.peak_tree_rss),
            "warnings": measured.warnings,
            "error": {key: measured.error.get(key) for key in ("type", "message", "frames")}
            if measured.error
            else None,
        }
        for measured in collected.spans
    ]
    llm = diagnostics.get(
        "llm", {key.removeprefix("llm_"): value for key, value in run.llm_metrics.items()}
    )
    from immich_memories.tracking.span_progress import uncovered_seconds

    data = {
        "uncovered_seconds": uncovered_seconds(collected.spans, run.total_duration_seconds),
        "version": diagnostics.get("version", __version__),
        "install_method": diagnostics.get("install_method", "unknown"),
        "tier": diagnostics.get("tier", "unknown"),
        "config_shape": {
            key: value
            for key, value in diagnostics.get("config_shape", {}).items()
            if key in {"llm", "location", "protocol"}
        },
        "missing_capabilities": diagnostics.get("missing_capabilities", []),
        "system": run.system_info.to_dict() if run.system_info else {},
        "run": {
            "id": run.run_id,
            "memory_type": run.memory_type,
            "source": run.source,
            "status": run.status,
            "wall_seconds": run.total_duration_seconds,
            "output_seconds": run.output_duration_seconds,
            "selected": run.clips_selected,
            "cache": diagnostics.get("cache", "unknown"),
        },
        "preflight": [
            {key: check.get(key) for key in ("name", "status", "message")}
            for check in diagnostics.get("preflight", [])
        ],
        "spans": spans,
        "phases": _phase_totals(spans, run.output_duration_seconds)
        or [
            {
                "name": phase.phase_name,
                "seconds": phase.duration_seconds,
                "items": phase.items_processed,
                "seconds_per_item": phase.duration_seconds / phase.items_processed
                if phase.items_processed
                else None,
                "seconds_per_output_second": phase.duration_seconds / run.output_duration_seconds
                if run.output_duration_seconds
                else None,
            }
            for phase in run.phases
        ],
        "llm": _usage(llm),
        "warnings": run.warnings,
        "selection_funnel": [
            {"stage": stage.get("stage")} | _numbers(stage, ("kept", "dropped", "input"))
            for stage in diagnostics.get("funnel", [])
        ],
        "logs": collected.logs,
        "log_counts": diagnostics.get("log_counts", {}),
    }
    if free_text := diagnostics.get("free_text"):
        from immich_memories.tracking.report_request import request_section

        data["free_text"] = request_section(
            free_text, privacy, include_captions=include_flagged_captions
        )
    return RunReport(privacy.clean(data))
