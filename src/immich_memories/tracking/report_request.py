"""Allowlisted diagnostics supplied by free-text memories (#1436), without their pictures."""

from immich_memories.tracking.report_privacy import ReportPrivacy

_ROLES = frozenset(
    {"son", "daughter", "child", "partner", "mother", "father", "parent", "friend", "sibling"}
)
_FIELDS = (
    "people",
    "when",
    "where",
    "text_in_photo",
    "shape",
    "subject",
    "alongside",
    "not_this",
    "words",
    "votes",
    "sources",
)
_VALUES = frozenset({"value", "word", "source", "votes", "options", "count", "answer"})
_COUNTS = (
    "in_scope",
    "pool",
    "captions_read",
    "yes",
    "unsure",
    "no",
    "photos_looked_at",
    "kept",
    "engine_picks",
    "film_seconds",
    "sample_agreement",
)


def _value(value):
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items() if key in _VALUES}
    if isinstance(value, list):
        return [_value(item) for item in value]
    return value


def _aliases(vocabulary: dict) -> dict[str, str]:
    aliases = {
        name: f"the owner's {role}" if role in _ROLES else "a person"
        for name, role in vocabulary.get("people", {}).items()
    }
    for group, label in (("homes", "home"), ("areas", "area"), ("text", "text")):
        for index, name in enumerate(vocabulary.get(group, []), 1):
            suffix = chr(64 + index) if group == "areas" and index <= 26 else str(index)
            aliases[name] = f"{label}{'-' if group == 'text' else ' '}{suffix}"
    return aliases


def request_section(record: dict, privacy: ReportPrivacy, *, include_captions: bool) -> dict:
    """Preserve the request's structure and verdicts, with captions an explicit opt-in."""
    flagged = record.get("flagged", [])
    privacy.include(
        ids=[row["asset_id"] for row in flagged if row.get("asset_id")],
        aliases=_aliases(record.get("privacy", {})),
    )
    # A reason quotes what the picture shows, so it is caption text and shares the opt-in.
    keys = ("asset_id", "stage", "verdict") + (("reason", "caption") if include_captions else ())
    return {
        "request": record.get("request", ""),
        # The translation as the owner read it: free text, so the aliases above redact it.
        "trace": record.get("trace", ""),
        "spec": {
            field: _value(record["spec"][field])
            for field in _FIELDS
            if field in record.get("spec", {})
        },
        "funnel": {
            key: value
            for key, value in record.get("funnel", {}).items()
            if key in _COUNTS and isinstance(value, (int, float))
        },
        "flagged": [{key: row[key] for key in keys if key in row} for row in flagged],
        "missing": record.get("missing", ""),
        "missing_check": {
            key: record["missing_check"][key]
            for key in ("offered", "picked", "in_pool", "read")
            if key in record.get("missing_check", {})
        },
        "captions_included": include_captions,
    }
