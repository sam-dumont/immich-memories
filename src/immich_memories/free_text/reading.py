"""Reading a request: the model splits its own words into who, when, where and what.

A 4B model asked open questions answers something rather than nothing, so it is never asked
to write words: it picks the request's own phrases from an enum of them. One answer is a
coin toss at that size, so the question is asked three times in three field orders and a
word belongs to a part when two answers put it there; answers that cut a phrase differently
("me" / "me and friends") still agree on the words.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from immich_memories.analysis.editorial_async_bridge import _run_sync
from immich_memories.analysis.llm_metrics import recording_stage
from immich_memories.analysis.llm_query import query_llm
from immich_memories.analysis.llm_wire import LLMIncompleteResponse
from immich_memories.config_models_llm import LLMConfig

if TYPE_CHECKING:
    from immich_memories.db import Store

PARTS = ("who", "when", "where", "what")
_LONGEST_PHRASE = 5
_READ_TOKENS = 600

_READ = """Split the owner's request by what it says about each of these, using the request's own
phrases. who: the people the photos show or are about. when: when the photos were taken. where:
where the photos were taken. what: what the photos show. A phrase can say more than one part.
Leave a part empty when the request says nothing about it. Return JSON."""

_WORD = re.compile(r"[\w'’]+")


class Asker(Protocol):
    """One question to the configured reader, answered in the JSON shape asked for."""

    def ask(
        self, prompt: str, schema: Mapping[str, Any], *, max_tokens: int
    ) -> Mapping[str, Any] | None:
        """The answer, or None when it was cut off or unreadable (never an empty answer)."""
        ...


class WireAsker:
    """Asks the configured reader through the product's LLM transport.

    The server is told the answer's JSON shape (a local server enforces it) and a reply cut
    off at its token limit is refused by the transport, so a half-written answer never
    reads as a short one. With `judgments`, an identical question is answered from the
    store instead of being asked again.
    """

    def __init__(self, config: LLMConfig, *, judgments: Store | None = None) -> None:
        self._config = config
        self._judgments = judgments

    def ask(
        self, prompt: str, schema: Mapping[str, Any], *, max_tokens: int
    ) -> Mapping[str, Any] | None:
        shape = {
            "type": "json_schema",
            "json_schema": {"name": "free_text_answer", "schema": schema, "strict": True},
        }
        try:
            with recording_stage("free_text"):
                # A running loop (the web server) cannot run another: the bridge uses a thread.
                raw = _run_sync(
                    query_llm(
                        prompt,
                        self._config,
                        temperature=0.0,
                        max_tokens=max_tokens,
                        timeout_seconds=self._config.timeout_seconds,
                        judgments=self._judgments,
                        require_complete=True,
                        response_format=shape,
                    )
                )
            answer = json.loads(raw)
        except (LLMIncompleteResponse, json.JSONDecodeError):
            return None
        return answer if isinstance(answer, dict) else None


@dataclass(frozen=True)
class Reading:
    """The request's phrases per part, and each of the three answers they were voted from."""

    request: str
    who: tuple[str, ...] = ()
    when: tuple[str, ...] = ()
    where: tuple[str, ...] = ()
    what: tuple[str, ...] = ()
    # One entry per field order; None when that answer was cut off even when asked again.
    answers: tuple[Mapping[str, tuple[str, ...]] | None, ...] = ()


def words_of(text: str) -> list[str]:
    """The request's words, lower-case, as the reading and the linking split them."""
    return _WORD.findall(text.lower())


def object_schema(**properties: Mapping[str, Any]) -> dict[str, Any]:
    """A JSON object whose every key is required: a small model skips an optional key."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties.copy(),
        "required": list(properties),
    }


def question(instruction: str, data: Mapping[str, Any]) -> str:
    """The prompt: the instruction, then the facts it is about as JSON."""
    return f"{instruction}\n\n{json.dumps(data, ensure_ascii=False, default=str)}"


def ask_again_if_cut(
    asker: Asker, prompt: str, schema: Mapping[str, Any], *, max_tokens: int
) -> Mapping[str, Any] | None:
    """Ask; a cut-off answer is asked once more, never read as "says nothing"."""
    for _ in range(2):
        answer = asker.ask(prompt, schema, max_tokens=max_tokens)
        if answer is not None:
            return answer
    return None


def three_orders(options: Sequence[str]) -> list[list[str]]:
    """The same options in three orders, so no answer leans on where an option stands."""
    items = list(options)
    return [items, items[::-1], items[1:] + items[:1]]


def read_request(request: str, asker: Asker) -> Reading:
    """Split the request into who, when, where and what spans of its own words, by vote."""
    tokens = words_of(request)
    grams = list(
        dict.fromkeys(
            " ".join(tokens[i : i + n])
            for n in range(1, _LONGEST_PHRASE + 1)
            for i in range(len(tokens) - n + 1)
        )
    )
    if not grams:
        return Reading(request=request)
    phrases = {"type": "array", "items": {"type": "string", "enum": grams}, "maxItems": 4}
    prompt = question(_READ, {"owner_request": request})
    votes: dict[str, Counter[int]] = {part: Counter() for part in PARTS}
    answers: list[Mapping[str, tuple[str, ...]] | None] = []
    for order in three_orders(PARTS):
        got = ask_again_if_cut(
            asker,
            prompt,
            object_schema(**dict.fromkeys(order, phrases)),
            max_tokens=_READ_TOKENS,
        )
        if got is None:
            answers.append(None)
            continue
        said = {part: tuple(p for p in got.get(part) or () if p in grams) for part in PARTS}
        answers.append(said)
        for part in PARTS:
            votes[part].update(_covered(tokens, said[part]))
    _vote_content(votes)
    spans = {part: _runs(tokens, votes[part]) for part in PARTS}
    return Reading(request=request, answers=tuple(answers), **spans)


def _covered(tokens: Sequence[str], phrases: Sequence[str]) -> set[int]:
    covered: set[int] = set()
    for phrase in phrases:
        words = phrase.split()
        for start in range(len(tokens) - len(words) + 1):
            if list(tokens[start : start + len(words)]) == words:
                covered |= set(range(start, start + len(words)))
    return covered


def _vote_content(votes: Mapping[str, Counter[int]]) -> None:
    # A named place is where the photos were taken and what they show, and answers split
    # "beaches" between the two. A word two answers call where-or-what is content: its part is
    # the one more answers gave it, and a tie is what (the subject).
    content = votes["where"] + votes["what"]
    for index, count in content.items():
        if count >= 2 and max(votes["where"][index], votes["what"][index]) < 2:
            side = "where" if votes["where"][index] > votes["what"][index] else "what"
            votes[side][index] = 2


def _runs(tokens: Sequence[str], votes: Counter[int]) -> tuple[str, ...]:
    kept = sorted(index for index, count in votes.items() if count >= 2)
    runs: list[list[int]] = []
    for index in kept:
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    return tuple(" ".join(tokens[i] for i in run) for run in runs)


def choose(
    asker: Asker,
    instruction: str,
    data: Mapping[str, Any],
    options: Sequence[str],
    *,
    max_tokens: int = 500,
) -> tuple[str, Counter[str]]:
    """One choice asked three times, the options in three orders: two votes win, else the first.

    The model reasons before it picks (a short `reason` key comes first in the answer).
    """
    votes: Counter[str] = Counter()
    if len(options) < 2:
        return options[0], votes
    for order in three_orders(options):
        got = ask_again_if_cut(
            asker,
            question(instruction, {**data, "options": order}),
            object_schema(
                reason={"type": "string", "maxLength": 200},
                choice={"type": "string", "enum": order},
            ),
            max_tokens=max_tokens,
        )
        if got is not None and got.get("choice") in options:
            votes[got["choice"]] += 1
    top = votes.most_common(1)
    return (top[0][0] if top and top[0][1] >= 2 else options[0]), votes


def choose_several(
    asker: Asker,
    instruction: str,
    data: Mapping[str, Any],
    options: Sequence[str],
    *,
    most: int,
    max_tokens: int = 500,
) -> tuple[list[str], Counter[str]]:
    """Up to `most` options asked three times, in three orders: an option two answers pick is kept.

    The kept options come in the order they were offered; none kept is an answer too (the
    caller decides what stands instead).
    """
    votes: Counter[str] = Counter()
    for order in three_orders(options):
        got = ask_again_if_cut(
            asker,
            question(instruction, {**data, "options": order}),
            object_schema(
                reason={"type": "string", "maxLength": 200},
                choices={
                    "type": "array",
                    "items": {"type": "string", "enum": order},
                    "maxItems": most,
                },
            ),
            max_tokens=max_tokens,
        )
        if got is not None:
            votes.update({choice for choice in got.get("choices") or () if choice in options})
    return [option for option in options if votes[option] >= 2], votes
