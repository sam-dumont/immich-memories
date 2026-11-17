"""What a span keeps of the text it carries before it leaves for the collector.

Two layers. `arguments` cleans a child program's argv as its span opens: paths cut to the file
name, ids replaced, and the values of the flags that name people or carry free text replaced
unless content capture is on. `redacted` is the last line before export, for every span an
instrumentation made too: paths cut and secrets redacted in the name, the attributes (list items
included), the events and the status, and a recorded traceback cut to the app's own frames.

Content capture is the switch the OpenTelemetry GenAI instrumentations share
(`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`): what turns on prompts and replies
turns on the names in program arguments too. Paths and secrets are never content.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from immich_memories.logging_config import redact_secrets
from immich_memories.tracking import otel

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import Event, ReadableSpan
    from opentelemetry.trace import Status

HIDDEN = otel.HIDDEN
# The CLI's text options whose value is a name (a person, an album, a group, an account), a
# date that identifies someone, or the user's own words. Keys the app builds from names
# (`--memory-key`, `--candidate`) count as names.
PRIVATE_FLAGS = frozenset(
    {
        "--account",
        "--accounts",
        "--album",
        "--ask",
        "--birthday",
        "-b",
        "--candidate",
        "--from-album",
        "--group",
        "--holiday",
        "--memory-key",
        "--missing",
        "--owner",
        "--people-expression",
        "--person",
        "-p",
        "--subject",
        "--subtitle",
        "--title",
    }
)
# Flags whose value is a credential: hidden even with content capture on.
SECRET_FLAGS = frozenset({"--api-key", "-k"})

# UUIDs, and long hex or digit runs (hashes, numeric ids): what makes one path every path.
IDS = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|\b[0-9a-fA-F]{16,}\b|\b\d{6,}\b"
)
# An absolute path of two or more parts outside a URL: `/home/x/store.db`, not `/api/v1`.
_PATHS = re.compile(
    r"(?<![\w:/.])(?:/(?:Users|home|var|private|tmp|data|mnt|srv|opt|root|Volumes)\b)(?:/[^\s/'\"]+)+"
)
# A caption FFmpeg draws: a place or a person's name inside a filter graph.
_DRAWN_TEXT = re.compile(r"(\btext=')[^']*'")
# One frame of a Python traceback, as `traceback.format_exc` writes it.
_FRAME = re.compile(
    r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<name>.+)$', re.MULTILINE
)
_APP = "immich_memories/"
# An exception's type as Python names it, dotted when qualified: `sqlite3.IntegrityError`.
_TYPE_NAME = re.compile(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*")
# ffmpeg filter graphs run to kilobytes; a span keeps the head of each and of the list.
_ARGUMENTS = 64
_ARGUMENT_CHARACTERS = 512


def cut_paths(text: str) -> str:
    """`text` with every absolute path in it cut to the file name."""
    return _PATHS.sub(lambda match: PurePath(match.group(0)).name, text)


def arguments(argv: Sequence[Any]) -> list[str]:
    """A child program's arguments as its span keeps them."""
    capture = otel.capturing_content()
    kept: list[str] = []
    owner: str | None = None
    for item in argv[:_ARGUMENTS]:
        text = redact_secrets(os.fsdecode(item))
        if owner is not None:
            kept.append(_private(owner, text, capture))
            owner = None
            continue
        flag, joined, value = text.partition("=")
        if flag in PRIVATE_FLAGS or flag in SECRET_FLAGS:
            kept.append(f"{flag}={_private(flag, value, capture)}" if joined else flag)
            owner = None if joined else flag
        elif joined and flag.startswith("--"):
            kept.append(f"{flag}={_plain(value, capture)}")
        else:
            kept.append(_plain(text, capture))
    return [IDS.sub("{id}", argument)[:_ARGUMENT_CHARACTERS] for argument in kept]


def _private(flag: str, value: str, capture: bool) -> str:
    return cut_paths(value) if capture and flag in PRIVATE_FLAGS else HIDDEN


def _plain(text: str, capture: bool) -> str:
    if not capture:
        text = _DRAWN_TEXT.sub(rf"\1{HIDDEN}'", text)
    if os.sep in text and not text.startswith("-"):
        # A path names a person's folders; the file name is what tells two steps apart.
        text = PurePath(text).name
    return text


def redacted(span: ReadableSpan) -> ReadableSpan:
    """`span` with paths cut and secrets redacted in all its text, tracebacks cut to app frames.

    The last line before export: an instrumentation that names a SQLite file, or an error that
    quotes a folder, would otherwise send a person's home layout to the collector.
    """
    from opentelemetry.sdk.trace import ReadableSpan

    # The app writes its own errors as content already (`otel.record_error`); an
    # instrumentation writes the error's own words, which hold whatever the error quoted.
    quoted = not otel.capturing_content() and _scope(span) != otel.SCOPE
    name = _clean(span.name)
    attributes = _clean_attributes(span.attributes or {})
    events = [_clean_event(event, quoted) for event in span.events]
    status = _clean_status(span.status, quoted)
    unchanged = (
        name == span.name
        and attributes == dict(span.attributes or {})
        and all(new is old for new, old in zip(events, span.events, strict=True))
        and status is span.status
    )
    if unchanged:
        return span
    return ReadableSpan(
        name=name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=attributes,
        events=events,
        links=span.links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


def _clean(text: str) -> str:
    return redact_secrets(cut_paths(text))


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, Sequence):
        return tuple(_clean(item) if isinstance(item, str) else item for item in value)
    return value


def _clean_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _clean_value(value) for key, value in attributes.items()}


def _scope(span: ReadableSpan) -> str:
    return span.instrumentation_scope.name if span.instrumentation_scope else ""


def _clean_event(event: Event, quoted: bool) -> Event:
    from opentelemetry.sdk.trace import Event

    attributes = dict(event.attributes or {})
    if isinstance(trace := attributes.get("exception.stacktrace"), str):
        attributes["exception.stacktrace"] = _app_frames(trace)
    if quoted and "exception.message" in attributes:
        attributes["exception.message"] = HIDDEN
    cleaned = _clean_attributes(attributes)
    if cleaned == dict(event.attributes or {}):
        return event
    return Event(event.name, cleaned, event.timestamp)


def _clean_status(status: Status, quoted: bool) -> Status:
    from opentelemetry.trace import Status

    if not status.description:
        return status
    description = _error_type(status.description) if quoted else _clean(status.description)
    if description == status.description:
        return status
    return Status(status.status_code, description)


def _error_type(description: str) -> str:
    # An instrumentation writes `Type: message` (FastAPI) or the driver's message alone
    # (SQLAlchemy, where Postgres adds `DETAIL: Key (name)=(...)`): keep the type, if any.
    head, colon, _ = description.partition(": ")
    return head if colon and _TYPE_NAME.fullmatch(head) else HIDDEN


def _app_frames(stacktrace: str) -> str:
    # Kept as `timing.describe_error` keeps them. Text that is no traceback (the frames
    # `otel.record_error` already wrote) stays as it is.
    frames = list(_FRAME.finditer(stacktrace))
    if not frames:
        return stacktrace
    return "\n".join(
        f"{frame['file'].split(_APP)[-1]}:{frame['line']}:{frame['name']}"
        for frame in frames
        if _APP in frame["file"]
    )
