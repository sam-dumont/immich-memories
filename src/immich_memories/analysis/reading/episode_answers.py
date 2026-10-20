"""Read a text episode answer with page-scoped label normalization.

Every reading is per page and per episode alias: a row the model invented, mislabelled or
contradicted is dropped and counted, and the page it belonged to is simply left unread.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TypeGuard

from immich_memories.analysis.judgments.strict_json import (
    bounded_model_text,
    final_json_object,
    without_trailing_commas,
)
from immich_memories.analysis.reading.cull_answer import CULL_BUCKETS
from immich_memories.store.episode_readings import (
    EpisodeCullDecision,
    EpisodeReadingIdentity,
    EpisodeRepresentative,
)

TEXT_EPISODE_SCHEMA_VERSION = "episode-reading-text-v1"
WHAT_HAPPENED_MAX_CHARS = 300
_REPRESENTATIVE_REASON_MAX_CHARS = 120


@dataclass(frozen=True)
class EpisodeRequestScope:
    identity: EpisodeReadingIdentity
    full_asset_ids: tuple[str, ...]
    page_asset_ids: tuple[str, ...]
    page_number: int
    page_count: int


@dataclass(frozen=True)
class EpisodePageReading:
    scope: EpisodeRequestScope
    what_happened: str
    representatives: tuple[EpisodeRepresentative, ...]
    cull_decisions: tuple[EpisodeCullDecision, ...]
    notable_moments: tuple[EpisodeRepresentative, ...] = ()


@dataclass(frozen=True)
class EpisodeResponseDiagnostic:
    """Content-free evidence for one response that needed conservative handling."""

    response_sha256: str
    unreadable_or_omitted_pages: int = 0
    discarded_invalid_representative_rows: int = 0
    discarded_invalid_cull_rows: int = 0
    discarded_conflicting_cull_rows: int = 0


@dataclass(frozen=True)
class TextEpisodeReadDiagnostics:
    """Inspectable normalizations without retaining private provider prose."""

    responses: tuple[EpisodeResponseDiagnostic, ...] = ()

    @property
    def discarded_invalid_representative_rows(self) -> int:
        return sum(response.discarded_invalid_representative_rows for response in self.responses)

    @property
    def discarded_invalid_cull_rows(self) -> int:
        return sum(response.discarded_invalid_cull_rows for response in self.responses)

    @property
    def discarded_conflicting_cull_rows(self) -> int:
        return sum(response.discarded_conflicting_cull_rows for response in self.responses)


@dataclass(frozen=True)
class _EpisodeResponse:
    readings: tuple[EpisodePageReading, ...]
    diagnostic: EpisodeResponseDiagnostic | None
    # What the reader wrote, and why each page it left unread was not read: a refusal keeps
    # both, so it can be explained after the fact (#2682).
    answer: str = ""
    problems: Mapping[tuple[str, int], str] = field(default_factory=dict)


@dataclass(frozen=True)
class _EpisodePageParse:
    reading: EpisodePageReading | None
    discarded_invalid_representative_rows: int = 0
    discarded_invalid_cull_rows: int = 0
    discarded_conflicting_cull_rows: int = 0
    problem: str = ""


def _unreadable(raw: str, scopes, problem: str) -> _EpisodeResponse:
    return _EpisodeResponse(
        (),
        EpisodeResponseDiagnostic(
            response_sha256=sha256(raw.encode("utf-8")).hexdigest(),
            unreadable_or_omitted_pages=len(scopes),
        ),
        answer=raw,
        problems={_page_key(scope): problem for scope in scopes},
    )


def _page_key(scope: EpisodeRequestScope) -> tuple[str, int]:
    return scope.identity.group_id, scope.page_number


def _json_problem(raw: str) -> str:
    """Why an answer holding no readable reading object could not be read."""
    if not raw.strip():
        return "the answer was empty"
    body = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        if exc.pos >= len(body) - 1 or exc.msg.startswith("Unterminated"):
            return "the answer stopped before its JSON was complete"
        return f"the answer was not valid JSON ({exc.msg} at line {exc.lineno} column {exc.colno})"
    return f'the answer had no object with schema_version "{TEXT_EPISODE_SCHEMA_VERSION}"'


def _rows_by_alias(values: list) -> dict[int, list[object]]:
    by_alias: dict[int, list[object]] = {}
    for value in values:
        if isinstance(value, dict) and _is_alias(value.get("episode")):
            by_alias.setdefault(value["episode"], []).append(value)
    return by_alias


def _response_diagnostic(response_hash, *, embedded, omitted, counts):
    invalid_representatives, invalid_cull, conflicting_cull = counts
    if not (embedded or omitted or invalid_representatives or invalid_cull or conflicting_cull):
        return None
    return EpisodeResponseDiagnostic(
        response_sha256=response_hash,
        unreadable_or_omitted_pages=omitted,
        discarded_invalid_representative_rows=invalid_representatives,
        discarded_invalid_cull_rows=invalid_cull,
        discarded_conflicting_cull_rows=conflicting_cull,
    )


def read_response_result(
    raw: str,
    scopes: tuple[EpisodeRequestScope, ...],
) -> _EpisodeResponse:
    """Every scope the answer read validly, plus what had to be discarded to get there."""
    payload, embedded = _episode_payload(raw)
    response_hash = sha256(raw.encode("utf-8")).hexdigest()
    if payload is None:
        return _unreadable(raw, scopes, _json_problem(raw))
    values = payload.get("episodes")
    if not isinstance(values, list):
        return _unreadable(raw, scopes, 'the answer had no "episodes" list')
    if not values:
        return _unreadable(raw, scopes, 'the answer\'s "episodes" list was empty')
    by_alias = _rows_by_alias(values)
    if any(alias > len(scopes) for alias in by_alias):
        # Numbered past the episodes asked: an entry per picture, not per episode, so even its
        # first row describes one picture rather than the episode it would be banked for.
        return _unreadable(
            raw,
            scopes,
            f'the answer had {len(values)} entries in "episodes" for {len(scopes)} episode(s)',
        )
    readings: list[EpisodePageReading] = []
    problems: dict[tuple[str, int], str] = {}
    discarded = [0, 0, 0]
    for episode_alias, scope in enumerate(scopes, start=1):
        matches = by_alias.get(episode_alias, [])
        if len(matches) != 1 or not isinstance(matches[0], dict):
            problems[_page_key(scope)] = (
                "the answer had no entry for this episode"
                if not matches
                else f"the answer had {len(matches)} entries for this episode"
            )
            continue
        parsed = _one_reading(matches[0], scope)
        discarded[0] += parsed.discarded_invalid_representative_rows
        discarded[1] += parsed.discarded_invalid_cull_rows
        discarded[2] += parsed.discarded_conflicting_cull_rows
        if parsed.reading is not None:
            readings.append(parsed.reading)
        else:
            problems[_page_key(scope)] = parsed.problem
    diagnostic = _response_diagnostic(
        response_hash,
        embedded=embedded,
        omitted=len(scopes) - len(readings),
        counts=discarded,
    )
    return _EpisodeResponse(tuple(readings), diagnostic, answer=raw, problems=problems)


def _episode_payload(raw: str) -> tuple[dict[str, object] | None, bool]:
    for text in dict.fromkeys((raw, without_trailing_commas(raw))):
        payload, embedded = _complete_payload(text)
        if payload is not None:
            return payload, embedded
    salvaged = _salvage_truncated_episodes(raw)
    return (salvaged, True) if salvaged is not None else (None, False)


def _complete_payload(raw: str) -> tuple[dict[str, object] | None, bool]:
    payload = final_json_object(raw)
    if payload is not None and payload.get("schema_version") == TEXT_EPISODE_SCHEMA_VERSION:
        return payload, False
    decoder = json.JSONDecoder()
    candidates: list[dict[str, object]] = []
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("schema_version") == TEXT_EPISODE_SCHEMA_VERSION:
            candidates.append(value)
    return (candidates[0], True) if len(candidates) == 1 else (None, False)


def _salvage_truncated_episodes(raw: str) -> dict[str, object] | None:
    """Recover whatever complete episode rows a cut-off transport finished writing.

    A reply truncated mid-array has already written zero or more whole `{...}` episode
    objects before the cut -- the outer envelope never closes, so the strict decoder
    above sees the whole thing as unparseable and every episode it read gets discarded
    with it. Measured 2026-09-29: 34 of 54 replies from a local gemma were truncated,
    and every one was thrown away whole. What is returned here becomes a page-scoped
    `episodes` payload carrying only the rows that finished; the alias loop in
    `read_response_result` leaves any episode this omits unread, so it still gets a
    retry -- this never invents or completes a row, it only stops discarding good ones.
    """
    marker = raw.find('"episodes"')
    if marker == -1:
        return None
    array_start = raw.find("[", marker)
    if array_start == -1:
        return None
    decoder = json.JSONDecoder()
    index = array_start + 1
    rows: list[object] = []
    length = len(raw)
    while index < length:
        while index < length and raw[index] in " \t\r\n,":
            index += 1
        if index >= length or raw[index] != "{":
            break
        try:
            value, index = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
            break
        rows.append(value)
    if not rows:
        return None
    return {"schema_version": TEXT_EPISODE_SCHEMA_VERSION, "episodes": rows}


def _one_reading(
    value: Mapping[str, object],
    scope: EpisodeRequestScope,
) -> _EpisodePageParse:
    what_happened = bounded_model_text(
        value.get("what_happened"), max_chars=WHAT_HAPPENED_MAX_CHARS
    )
    representatives, discarded_representatives = _representatives(
        value.get("representatives"), scope.page_asset_ids
    )
    if what_happened is None or not representatives:
        return _EpisodePageParse(
            None,
            discarded_invalid_representative_rows=discarded_representatives,
            problem=(
                "its what_happened was missing or not one plain line"
                if what_happened is None
                else "it named no usable representative"
            ),
        )
    # A page may name a record on any of its own pictures, so this list is not capped at
    # three the way the representatives are: it is not a choice of which frames to show.
    notable_moments, _discarded = _representatives(
        value.get("notable_moments"), scope.page_asset_ids, limit=len(scope.page_asset_ids)
    )
    cull_decisions, discarded_invalid, discarded_conflicting = _cull_decisions(
        value.get("cull"),
        scope.page_asset_ids,
        # A picture the reading calls a record of something cannot also be a Cull reject.
        representative_ids=frozenset(
            item.asset_id for item in (*representatives, *notable_moments)
        ),
    )
    return _EpisodePageParse(
        EpisodePageReading(
            scope=scope,
            what_happened=what_happened,
            representatives=representatives,
            cull_decisions=cull_decisions,
            notable_moments=notable_moments,
        ),
        discarded_invalid_representative_rows=discarded_representatives,
        discarded_invalid_cull_rows=discarded_invalid,
        discarded_conflicting_cull_rows=discarded_conflicting,
    )


def _representative_named(item: object, asset_ids: tuple[str, ...]) -> tuple[str, str] | None:
    """The asset and reason one representative row names, or None when it names neither."""
    if not isinstance(item, dict):
        return None
    asset_alias = item.get("asset")
    if isinstance(asset_alias, str):
        label = asset_alias.removeprefix("asset ")
        asset_alias = next(
            (index for index in range(1, len(asset_ids) + 1) if str(index) == label), None
        )
    if not _is_alias(asset_alias):
        return None
    reason = bounded_model_text(item.get("reason"), max_chars=_REPRESENTATIVE_REASON_MAX_CHARS)
    if reason is None or not 1 <= asset_alias <= len(asset_ids):
        return None
    return asset_ids[asset_alias - 1], reason


def _representatives(
    value: object,
    asset_ids: tuple[str, ...],
    *,
    limit: int = 3,
) -> tuple[tuple[EpisodeRepresentative, ...], int]:
    if not isinstance(value, list):
        return (), 1
    representatives: list[EpisodeRepresentative] = []
    seen: set[str] = set()
    discarded = 0
    for item in value:
        named = _representative_named(item, asset_ids)
        if named is None or named[0] in seen or len(representatives) == limit:
            discarded += 1
            continue
        seen.add(named[0])
        representatives.append(EpisodeRepresentative(*named))
    return tuple(representatives), discarded


def _cull_named(item: object, asset_ids: tuple[str, ...]) -> tuple[str, str] | None:
    """The asset and bucket one cull row names, or None when it names neither."""
    if (
        not isinstance(item, dict)
        or not _is_alias(item.get("asset"))
        or item.get("bucket") not in CULL_BUCKETS
        or not 1 <= item["asset"] <= len(asset_ids)
    ):
        return None
    return asset_ids[item["asset"] - 1], str(item["bucket"])


def _cull_decisions(
    value: object,
    asset_ids: tuple[str, ...],
    *,
    representative_ids: frozenset[str],
) -> tuple[tuple[EpisodeCullDecision, ...], int, int]:
    if value is None:
        # The lean question asks for no Cull at all; an absent list is no rejects, not a bad row.
        return (), 0, 0
    if not isinstance(value, list):
        return (), 1, 0
    decisions: list[EpisodeCullDecision] = []
    seen: set[str] = set()
    discarded_invalid = 0
    discarded_conflicting = 0
    for item in value:
        named = _cull_named(item, asset_ids)
        if named is None:
            discarded_invalid += 1
        elif named[0] in representative_ids:
            discarded_conflicting += 1
        elif named[0] in seen:
            discarded_invalid += 1
        else:
            seen.add(named[0])
            decisions.append(EpisodeCullDecision(*named))
    return tuple(decisions), discarded_invalid, discarded_conflicting


def _is_alias(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
