"""Exact casefolded literal matching for provider-facing privacy gates."""

import re
from collections.abc import Callable


def private_token_matcher(tokens: frozenset[str]) -> Callable[[str], bool]:
    """Compile literal substring checks once per annotation cohort.

    Identifier prefixes are already part of the privacy policy. Indexing them
    avoids searching every line once for every identifier in a large period.
    Longer identifiers still require their full literal match; an index prefix
    alone never withholds a line unless it is itself a policy token.
    """
    if not tokens:
        return lambda _text: False
    width = min(8, min(map(len, tokens)))
    if not width:
        return lambda _text: True
    terminal = frozenset(token for token in tokens if len(token) == width)
    longer: dict[str, list[str]] = {}
    for token in tokens:
        prefix = token[:width]
        if prefix not in terminal:
            longer.setdefault(prefix, []).append(token)

    alphabet = "".join(sorted({char for token in tokens for char in token[:width]}))
    candidates = re.compile(rf"(?=([{re.escape(alphabet)}]{{{width}}}))")

    def contains(text: str) -> bool:
        rendered = text.casefold()
        for match in candidates.finditer(rendered):
            prefix = match[1]
            if prefix in terminal:
                return True
            matches = longer.get(prefix)
            if matches and any(rendered.startswith(token, match.start()) for token in matches):
                return True
        return False

    return contains
