"""The grandfathered-complexity list is a ratchet, not a bucket.

`make cognitive-complexity` passes when the watermark says every violation was
already there. When the gate regenerated its own baseline, a change that pushed a
function over the limit was silently absolved: the hook rewrote the file, the gate
compared against the rewritten version, and the allowance grew by one. It reached
36 functions that way, from 13.

This test is the thing that notices. It has no opinion about which functions are
grandfathered -- only that the count cannot climb without someone raising the
number below on purpose, in a commit that says so.
"""

from __future__ import annotations

import json
from pathlib import Path

WATERMARK = Path(__file__).resolve().parent.parent / "complexity-watermark.json"

# Lower this when the count drops. Never raise it to make a red build green:
# extract a helper instead, which is what the gate is asking for.
MAX_GRANDFATHERED_FUNCTIONS = 35


def test_the_grandfathered_complexity_list_never_grows() -> None:
    watermark = json.loads(WATERMARK.read_text())
    functions = [c for names in watermark.values() for found in names.values() for c in found]

    assert len(functions) <= MAX_GRANDFATHERED_FUNCTIONS, (
        f"{len(functions)} functions are over the cognitive-complexity limit, "
        f"above the agreed {MAX_GRANDFATHERED_FUNCTIONS}. The watermark was "
        f"regenerated, which silently widens the allowance. Simplify the new "
        f"offender, or raise MAX_GRANDFATHERED_FUNCTIONS deliberately."
    )
