"""What the pool asks the model about the request: text only, never a picture.

Each question offers the request's own words or the library's words and is voted three times;
grammar gates each one, so a request that says nothing of the kind asks nothing.
"""

from __future__ import annotations

import re
from collections import Counter

from immich_memories.free_text.linking import GLUE, Reason
from immich_memories.free_text.reading import Asker, choose_several

_LEAVE_OUT = """Which of these phrases from the request name what the owner asks to leave out of the
film? None when the request excludes nothing. Reason first. Return JSON."""
# Only what follows a negation can be left out: asked over the whole request, the model left
# out the subject itself ("garden" out of "our garden").
_NEGATED = re.compile(r"\b(?:not|no|without|except|excluding)\b([^.;!?]*)")
_NEGATED_WORD = re.compile(r"[a-z][a-z'’-]*")
_MOST_LEFT_OUT = 4
_MOST_OFFERED = 40


def left_out(request: str, asker: Asker) -> tuple[tuple[str, ...], Reason | None]:
    """The phrases the request asks to leave out, picked by the model from what follows a
    negation ("no toy cars"); nothing asked when the request negates nothing."""
    grams: list[str] = []
    for span in _NEGATED.findall(request.lower()):
        tokens = _NEGATED_WORD.findall(span)
        grams += [
            " ".join(tokens[i : i + n])
            for n in (1, 2, 3)
            for i in range(len(tokens) - n + 1)
            if not set(tokens[i : i + n]) <= GLUE
        ]
    offered = list(dict.fromkeys(grams))[:_MOST_OFFERED]
    if not offered:
        return (), None
    picked, votes = choose_several(
        asker, _LEAVE_OUT, {"owner_request": request}, offered, most=_MOST_LEFT_OUT
    )
    reason = Reason(
        "; ".join(_NEGATED.findall(request.lower())).strip(),
        f"only what follows a negation; the model picked ({tally(votes)})",
        f"leave out {', '.join(picked)}" if picked else "nothing left out",
    )
    return tuple(picked), reason


def tally(votes: Counter[str]) -> str:
    """The votes as the trace prints them."""
    return ", ".join(f"{word} {count}/3" for word, count in votes.most_common()) or "no answer"
