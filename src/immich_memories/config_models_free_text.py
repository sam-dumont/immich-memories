"""Free-text memories: a film asked for in a sentence."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

# WordNet 3.0 as nltk distributes it, at a fixed commit of nltk_data so the bytes never move;
# `models fetch` checks them against the digest pinned in free_text/lexicon.py.
WORDNET_URL = (
    "https://raw.githubusercontent.com/nltk/nltk_data/"
    "550b6625bcef1f2abff2ff770a5a0d272c9c6b2a/packages/corpora/wordnet.zip"
)


class FreeTextConfig(BaseModel):
    """The word knowledge a request in a sentence is read with."""

    wordnet: str = Field(
        default="~/.immich-memories/models/wordnet/wordnet.zip",
        description=(
            "The WordNet 3.0 corpus (11 MB, digest-pinned in code) a request's words are "
            "looked up in; `models fetch` downloads it here"
        ),
    )
    wordnet_url: str = Field(
        default=WORDNET_URL,
        description="Where `models fetch` downloads the pinned WordNet corpus from",
    )

    @property
    def wordnet_path(self) -> Path:
        return Path(self.wordnet).expanduser()
