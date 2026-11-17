"""How an episode request is cut into pages under the model's limits.

Each episode is asked on its own; an episode too large for one prompt is split into pages of its
own, each asked on its own, and every answer is budgeted for the rows it may hold.
"""

from __future__ import annotations

from dataclasses import dataclass

from immich_memories.analysis.reading.episode_answers import EpisodeRequestScope
from immich_memories.analysis.reading.episode_block import picture_line
from immich_memories.analysis.reading.episode_prompt import EpisodePromptFacts, episode_prompt
from immich_memories.store.episode_readings import EpisodeReadingIdentity

TEXT_EPISODE_MAX_OUTPUT_TOKENS = 4_000
_DEFAULT_MAX_PROMPT_CHARS = 24_000
_DEFAULT_MIN_OUTPUT_TOKENS = 512
_DEFAULT_OUTPUT_BASE_TOKENS = 200
_DEFAULT_OUTPUT_TOKENS_PER_ROW = 160
# Measured 2026-09-29 on a local gemma reading an unfiltered month (prepare --overviews):
# 63% of replies were truncated, most well under the 4,000-token ceiling -- the old
# estimate (12) only covers a bare cull row and starves the per-asset cost a model
# actually pays once it writes a representative or notable-moment reason (up to 120
# chars) for some fraction of a page's pictures. This still assumes most assets get the
# cheap row, not the expensive one; it is a safety margin, not a worst case.
_DEFAULT_OUTPUT_TOKENS_PER_ASSET = 28


@dataclass(frozen=True)
class TextEpisodeRequestLimits:
    """Bound one serialized episode request below the model's safe context."""

    max_prompt_chars: int = _DEFAULT_MAX_PROMPT_CHARS
    max_assets_per_page: int = 90
    max_output_tokens: int = TEXT_EPISODE_MAX_OUTPUT_TOKENS
    min_output_tokens: int = _DEFAULT_MIN_OUTPUT_TOKENS
    output_base_tokens: int = _DEFAULT_OUTPUT_BASE_TOKENS
    output_tokens_per_row: int = _DEFAULT_OUTPUT_TOKENS_PER_ROW
    output_tokens_per_asset: int = _DEFAULT_OUTPUT_TOKENS_PER_ASSET
    unread_retry_rounds: int = 2

    def __post_init__(self) -> None:
        if (
            self.max_prompt_chars <= 0
            or self.max_assets_per_page <= 0
            or self.max_output_tokens <= 0
            or self.min_output_tokens <= 0
            or self.output_base_tokens <= 0
            or self.output_tokens_per_row <= 0
            or self.output_tokens_per_asset <= 0
            or self.unread_retry_rounds < 0
        ):
            raise ValueError("episode request limits must be positive")
        if self.min_output_tokens > self.max_output_tokens:
            raise ValueError("episode minimum output budget cannot exceed its ceiling")


def episode_page_scopes(
    identity: EpisodeReadingIdentity,
    full_asset_ids: tuple[str, ...],
    *,
    max_assets_per_page: int,
    facts: EpisodePromptFacts,
    max_prompt_chars: int,
) -> tuple[EpisodeRequestScope, ...]:
    whole = EpisodeRequestScope(
        identity=identity,
        full_asset_ids=full_asset_ids,
        page_asset_ids=full_asset_ids,
        page_number=1,
        page_count=1,
    )
    whole_prompt = episode_prompt(whole, facts)
    if len(full_asset_ids) <= max_assets_per_page and len(whole_prompt) <= max_prompt_chars:
        return (whole,)

    # A page's prompt is the question, a header of facts said once and one numbered line per
    # picture. The header is sized from the whole episode, whose towns and people include every
    # page's, with the longest page note; a page's length is then that plus its own lines, so
    # the prompt is rendered once, not per picture.
    conservative = max(len(full_asset_ids), 2)
    whole_lines = len("\n".join(_lines(full_asset_ids, facts)))
    page_note = len(f" (page {conservative} of {conservative})")
    fixed = len(whole_prompt) - whole_lines + page_note
    pages: list[tuple[str, ...]] = []
    current: tuple[str, ...] = ()
    lines_chars = 0
    for asset_id in full_asset_ids:
        position = len(current) + 1
        proposed_chars = (
            lines_chars + (1 if current else 0) + len(picture_line(position, facts.lines[asset_id]))
        )
        if current and (
            position > max_assets_per_page or fixed + proposed_chars > max_prompt_chars
        ):
            pages.append(current)
            current = (asset_id,)
            lines_chars = len(picture_line(1, facts.lines[asset_id]))
        else:
            current = (*current, asset_id)
            lines_chars = proposed_chars
    if current:
        pages.append(current)

    return tuple(
        EpisodeRequestScope(
            identity=identity,
            full_asset_ids=full_asset_ids,
            page_asset_ids=page_asset_ids,
            page_number=page_number,
            page_count=len(pages),
        )
        for page_number, page_asset_ids in enumerate(pages, start=1)
    )


def _lines(asset_ids: tuple[str, ...], facts: EpisodePromptFacts) -> list[str]:
    return [
        picture_line(number, facts.lines[asset_id])
        for number, asset_id in enumerate(asset_ids, start=1)
    ]


def pack_episode_scopes(
    scopes: tuple[EpisodeRequestScope, ...],
    facts: EpisodePromptFacts,
    *,
    limits: TextEpisodeRequestLimits,
) -> tuple[tuple[tuple[EpisodeRequestScope, ...], ...], tuple[EpisodeRequestScope, ...]]:
    """One request per page, and the pages no request can hold.

    The question reads one episode: asked about several at once, the small reader wrote an
    entry per picture or merged them (#2594).
    """
    packs: list[tuple[EpisodeRequestScope, ...]] = []
    oversized: list[EpisodeRequestScope] = []
    for scope in scopes:
        if (
            len(episode_prompt(scope, facts)) > limits.max_prompt_chars
            or episode_completion_budget((scope,), limits) > limits.max_output_tokens
        ):
            oversized.append(scope)
        else:
            packs.append((scope,))
    return tuple(packs), tuple(oversized)


def episode_completion_budget(
    scopes: tuple[EpisodeRequestScope, ...],
    limits: TextEpisodeRequestLimits,
) -> int:
    """Size generation from demanded response rows and possible Cull aliases."""
    estimated = (
        limits.output_base_tokens
        + limits.output_tokens_per_row * len(scopes)
        + limits.output_tokens_per_asset * sum(len(scope.page_asset_ids) for scope in scopes)
    )
    return max(limits.min_output_tokens, estimated)
