"""What the episode reader asks, and the facts a reading may take a name from."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256

from immich_memories.analysis.reading.episode_answers import EpisodeRequestScope
from immich_memories.analysis.reading.episode_block import episode_block

AlbumNames = Callable[[Sequence[str]], tuple[str, ...]]

# One episode per call, its facts said once (#2594). The question is the one that won a measured
# A/B on a real library with the small reader: against the old three-task prompt over raw lines
# it was a third of the size and the time, named a person or a town in 71 answers of 76 instead
# of 57, and wrote a generic sentence once instead of 22 times.
_INTRO = """Read one episode from a family's photo library: pictures taken close together, each
listed with what it shows. Use only these facts; do not invent names, places or events. Text
read off a sign, a shirt or a screen names that object, not the place or the event.
"""

_WHAT_HAPPENED = """- what_happened: one plain sentence of at most 25 words: the episode's main activity with its most
  specific thing (a cake, a swim, a castle), who was there by first name (at most three), and
  the main town. Say what people did, or with no one there, what is there (a
  view, a car); never "various" or "spent time together".
- representatives: the 1 to 3 pictures that best show it, by number, each with a reason of at
  most six words. Prefer a starred picture, a video or a live photo when it shows the moment.
"""

# The polish layer seats and protects an episode's records, so a film's on-demand reading asks
# for them too. The ask names notable_moments where it says "[]": a bare "Return []" was read as
# the whole answer (#2682).
_NOTABLE = """- notable_moments: the pictures that record something that happens once, by number, each
  with what it records: an arrival (a birth, a new pet, a new home), a milestone with its
  occasion visible (a named birthday, a first day, a graduation, a wedding, a trophy), a change
  you can see (a new haircut, a cast, a finished build), text naming the occasion, or an object
  that is the record itself (a ring in its box, a hospital bracelet). An outing, a view, a meal,
  a pose, a game, a portrait or an animal is not one, and nor is a first guessed from the order
  of the pictures. notable_moments is [] when no picture shows one; that is the usual answer.
"""

# Library preparation only: the Cull pass reads these rejects.
_CULL = """- cull: only genuine rejects, by number, each with a bucket: notes (screens, documents,
  receipts), failed (the picture did not come out) or foreign (saved imagery not from this
  life). Similar or merely ordinary pictures are not rejects; cull is [] when there are none.
"""

_ANSWER = (
    '"what_happened":"...","representatives":[{"picture":1,"reason":"..."}],'
    '"notable_moments":[{"picture":1,"reason":"what this is a record of"}]'
)

_LEAN_PROMPT = (
    f"{_INTRO}\nAnswer three things:\n{_WHAT_HAPPENED}{_NOTABLE}\nJSON only: {{{_ANSWER}}}"
)
_PROMPT = (
    f"{_INTRO}\nAnswer four things:\n{_WHAT_HAPPENED}{_NOTABLE}{_CULL}\n"
    f'JSON only: {{{_ANSWER},"cull":[{{"picture":2,"bucket":"notes"}}]}}'
)

_PROMPT_NAME = "episode-prompt-v5-slim"
_LEAN_PROMPT_NAME = "episode-prompt-v5-slim-lean"

# A banked answer is ground truth for the question that was asked. Hashing the prompt into the
# producer expires every reading the moment its wording changes, whether or not the name above
# was bumped with it.
TEXT_EPISODE_PROMPT_VERSION = f"{_PROMPT_NAME}/{sha256(_PROMPT.encode()).hexdigest()[:16]}"
TEXT_EPISODE_LEAN_PROMPT_VERSION = (
    f"{_LEAN_PROMPT_NAME}/{sha256(_LEAN_PROMPT.encode()).hexdigest()[:16]}"
)


@dataclass(frozen=True, slots=True)
class EpisodePromptFacts:
    """Everything an episode block is rendered from besides the scope itself."""

    lines: Mapping[str, str]
    album_names: AlbumNames | None = None
    # The film's on-demand question: no Cull.
    lean: bool = False

    def albums(self, asset_ids: Sequence[str]) -> tuple[str, ...]:
        """The albums holding these assets; none when no album holds them."""
        return () if self.album_names is None else tuple(self.album_names(asset_ids))


def episode_prompt(scope: EpisodeRequestScope, facts: EpisodePromptFacts) -> str:
    """Render one request: the question, then the block for one episode or one page of it."""
    block = episode_block(
        [facts.lines[asset_id] for asset_id in scope.page_asset_ids],
        # The album holds the whole episode, not just this page of it.
        albums=facts.albums(scope.full_asset_ids),
        page=(scope.page_number, scope.page_count) if scope.page_count > 1 else None,
    )
    return f"{_LEAN_PROMPT if facts.lean else _PROMPT}\n\n{block}"


def episode_retry_prompt(
    scope: EpisodeRequestScope, facts: EpisodePromptFacts, problem: str
) -> str:
    """The episode asked again, told what made its last answer unusable.

    At temperature 0 the same question earns the same answer byte for byte: the recorded
    refusals got it three times running. Naming the problem is what changes the answer.
    """
    return (
        f"{episode_prompt(scope, facts)}\n\nYour last answer could not be used: {problem}. "
        "Answer again with the JSON object only."
    )
