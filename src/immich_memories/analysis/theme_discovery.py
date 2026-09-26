"""Caption-grounded video briefs, with exact source membership and honest coverage."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from immich_memories.config_loader import Config
from immich_memories.store.theme_captions import ThemeCaption

PROMPT_VERSION = "caption-stories-v2"


class ThemeCandidate(BaseModel):
    """A reviewable proposal with source witnesses and the complete owner brief."""

    key: str
    title: str
    brief: str
    interpretation: str
    evidence: tuple[ThemeCaption, ...]

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """Only witnessed sources may enter this subject's film."""
        return tuple(row.asset_id for row in self.evidence)

    @property
    def occurrences(self) -> int:
        """Count separate capture days, rather than burst volume."""
        return len({row.taken_at.date() for row in self.evidence})

    @property
    def years(self) -> tuple[int, ...]:
        """Report witnessed years, without filling gaps in the record."""
        return tuple(sorted({row.taken_at.year for row in self.evidence}))


class ThemeResult(BaseModel):
    """A partial scan stays partial; no unscreened source counts as rejected."""

    version: str = PROMPT_VERSION
    total_assets: int
    captioned_assets: int
    reviewed_assets: int = 0
    candidates: tuple[ThemeCandidate, ...] = ()

    @property
    def partial(self) -> bool:
        """Distinguish the reviewed prefix from the complete caption corpus."""
        return self.reviewed_assets < self.captioned_assets


def require_theme_support(config: Config | None) -> None:
    """Refuse before store reads or provider calls on reduced tiers."""
    if (
        config is None
        or config.editorial.preparation.tier != "full"
        or not config.llm.model.strip()
        or config.editorial.reader == "rules"
    ):
        raise ValueError(
            "Theme memories require the full preparation tier and a configured model reader"
        )


def find_theme(
    config: Config,
    brief: str,
    *,
    since: int = 1,
    until: int = 9999,
    max_pages: int | None = None,
    requester: Callable[[str], str] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ThemeResult:
    """Read every scoped caption against the original brief, without a keyword shortlist.

    A page budget pauses after that many new pages. Repeating the same request
    reuses validated pages and continues from there. No brief text is truncated.
    """
    from immich_memories.analysis.story_discovery import scan_captions

    if not brief.strip():
        raise ValueError("Write a subject or a brief first")
    return scan_captions(
        config,
        brief=brief,
        since=since,
        until=until,
        max_pages=max_pages,
        requester=requester,
        progress=progress,
    )
