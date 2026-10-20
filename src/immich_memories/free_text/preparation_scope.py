"""Which pictures of a window a request's place can keep, so only those are prepared (#2749).

Preparing captions is the expensive step, and a place the library's own metadata settles
(at home, near home) drops most of a window before any caption is read. The test here is the
pool's own (`scopes.in_place`, with the pool's own GPS rule), so preparation and pool cannot
disagree: a picture the pool could keep is prepared, and one the scope always drops is not.
A request whose place metadata cannot settle keeps today's behaviour: the whole window.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from immich_memories.api.models import Asset, VideoClipInfo
from immich_memories.config.models.automation import TripsConfig
from immich_memories.free_text.facts import TripRules
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture
from immich_memories.free_text.linking import Household
from immich_memories.free_text.pool import PrintedText, Translation, needs_gps
from immich_memories.free_text.pool_questions import printed_words
from immich_memories.free_text.reading import Asker
from immich_memories.free_text.scopes import PER_PICTURE_SCOPES, in_place

# The ids, among the pictures given, that the request's place could keep.
PlaceFilter = Callable[[Sequence[LibraryPicture]], frozenset[str]]


def place_filter(
    translation: Translation,
    household: Household,
    lexicon: Lexicon,
    asker: Asker,
    *,
    trips: TripRules | None = None,
    printed: PrintedText | None = None,
) -> PlaceFilter | None:
    """The place test for a window's pictures; None when metadata alone cannot decide it."""
    if translation.where.scope not in PER_PICTURE_SCOPES or translation.facts.places:
        return None
    if (
        printed
        and printed_words(
            translation.reading.request, translation.reading.when, translation.subject, asker
        )[0]
    ):
        # A printed word makes its episodes the scope, not the place (pool `_printed`).
        return None
    require_gps, _why = needs_gps(translation, lexicon, asker)
    rules = trips or TripsConfig()

    def keeps(pictures: Sequence[LibraryPicture]) -> frozenset[str]:
        placed = in_place(
            translation.where, pictures, household.homes, rules, require_gps=require_gps
        )
        # `in_place` says anywhere only for a scope this filter never offers.
        kept = placed[0] if placed else pictures
        return frozenset(picture.asset_id for picture in kept)

    return keeps


def picture_of(source: Asset | VideoClipInfo) -> LibraryPicture:
    """What the library will hold about a window's picture once it is stored: its date,
    kind and GPS, read the way `remember_assets` stores them."""
    asset = source.asset if isinstance(source, VideoClipInfo) else source
    exif = asset.exif_info
    taken = (
        (exif.date_time_original if exif else None)
        or asset.local_date_time
        or asset.file_created_at
    )
    return LibraryPicture(
        asset_id=asset.id,
        taken_at=taken,
        media_kind="video" if asset.is_video else "photo",
        latitude=exif.latitude if exif else None,
        longitude=exif.longitude if exif else None,
    )
