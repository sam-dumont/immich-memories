"""Byte-identical copies under different asset IDs count once (#1500, slice 4)."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime

from immich_memories.analysis.exact_copies import fold_exact_copies
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.api.models import Asset, AssetType, Person
from immich_memories.api.person_expression import parse_person_expression
from tests.conftest import make_asset

_TAKEN = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)


def _sha1(content: str) -> str:
    """Immich's wire form: the file's SHA-1, base64-encoded."""
    return base64.b64encode(hashlib.sha1(content.encode()).digest()).decode()  # noqa: S324


def _photo(
    asset_id: str,
    *,
    owner: str = "owner-a",
    checksum: str | None = None,
    favourite: bool = False,
    people: tuple[str, ...] = (),
    companion: str | None = None,
    kind: AssetType = AssetType.IMAGE,
) -> Asset:
    asset = make_asset(asset_id, is_favorite=favourite, file_created_at=_TAKEN)
    return asset.model_copy(
        update={
            "type": kind,
            "owner_id": owner,
            "checksum": checksum,
            "people": [Person(id=person) for person in people],
            "live_photo_video_id": companion,
        }
    )


def _ids(pool) -> list[str]:
    return [source.id for source in pool]


def test_two_ids_holding_the_same_bytes_count_once() -> None:
    bytes_ = _sha1("beach.jpg")

    folded = fold_exact_copies(
        (_photo("b-copy", checksum=bytes_), _photo("a-copy", checksum=bytes_)),
        primary_owner_id=None,
    )

    assert _ids(folded.pool) == ["a-copy"]
    [group] = folded.groups
    assert group.representative_id == "a-copy"
    assert {reference.asset_id for reference in group.references} == {"a-copy", "b-copy"}
    assert group.content_key != group.representative_id


def test_a_favourited_copy_is_the_one_kept() -> None:
    bytes_ = _sha1("beach.jpg")

    folded = fold_exact_copies(
        (
            _photo("a-copy", owner="owner-a", checksum=bytes_),
            _photo("z-copy", owner="owner-z", checksum=bytes_, favourite=True),
        ),
        primary_owner_id="owner-a",
    )

    assert _ids(folded.pool) == ["z-copy"]
    assert folded.pool[0].is_favorite


def test_without_a_favourite_the_primary_owners_copy_is_kept() -> None:
    bytes_ = _sha1("beach.jpg")
    copies = (
        _photo("a-copy", owner="owner-a", checksum=bytes_),
        _photo("z-copy", owner="owner-z", checksum=bytes_),
    )

    assert _ids(fold_exact_copies(copies, primary_owner_id="owner-z").pool) == ["z-copy"]
    assert _ids(fold_exact_copies(copies, primary_owner_id=None).pool) == ["a-copy"]


def test_without_a_favourite_or_primary_owner_the_smallest_owner_then_id_is_kept() -> None:
    bytes_ = _sha1("beach.jpg")

    folded = fold_exact_copies(
        (
            _photo("a-copy", owner="owner-b", checksum=bytes_),
            _photo("z-copy", owner="owner-a", checksum=bytes_),
            _photo("m-copy", owner="owner-a", checksum=bytes_),
        ),
        primary_owner_id="someone-else",
    )

    assert _ids(folded.pool) == ["m-copy"]


def test_the_same_uuid_twice_is_left_to_the_first_step() -> None:
    """Same-UUID coalescing runs first; this rule only ever sees distinct IDs folded."""
    bytes_ = _sha1("beach.jpg")
    once = _photo("a-copy", checksum=bytes_)

    folded = fold_exact_copies((once,), primary_owner_id=None)

    assert _ids(folded.pool) == ["a-copy"]
    assert folded.groups == ()


def test_a_missing_empty_or_foreign_checksum_never_folds() -> None:
    sources = (
        _photo("no-checksum", checksum=None),
        _photo("also-none", checksum=None),
        _photo("empty", checksum=""),
        _photo("also-empty", checksum="  "),
        _photo("fake", checksum="fake-checksum"),
        _photo("also-fake", checksum="fake-checksum"),
    )

    folded = fold_exact_copies(sources, primary_owner_id=None)

    assert len(folded.pool) == 6
    assert folded.groups == ()


def test_a_photo_and_a_video_with_equal_checksums_stay_two_items() -> None:
    bytes_ = _sha1("beach")

    folded = fold_exact_copies(
        (
            _photo("still", checksum=bytes_),
            _photo("clip", checksum=bytes_, kind=AssetType.VIDEO),
        ),
        primary_owner_id=None,
    )

    assert _ids(folded.pool) == ["clip", "still"]


def test_different_bytes_never_fold_even_at_the_same_instant() -> None:
    folded = fold_exact_copies(
        (_photo("original", checksum=_sha1("full")), _photo("export", checksum=_sha1("edited"))),
        primary_owner_id=None,
    )

    assert _ids(folded.pool) == ["export", "original"]


def test_reversed_page_order_gives_the_same_pool_and_groups() -> None:
    bytes_ = _sha1("beach.jpg")
    pages = (
        _photo("a-copy", owner="owner-b", checksum=bytes_),
        _photo("b-copy", owner="owner-a", checksum=bytes_, people=("kid-1",)),
        _photo("c-other", checksum=_sha1("other")),
        _photo("d-copy", owner="owner-c", checksum=bytes_, people=("kid-2",)),
    )

    forward = fold_exact_copies(pages, primary_owner_id="owner-a")
    backward = fold_exact_copies(pages[::-1], primary_owner_id="owner-a")

    assert forward == backward
    assert _ids(forward.pool) == ["b-copy", "c-other"]


def _holding(pool, expression: str) -> frozenset[str]:
    """The items one expression holds on, each item judged on its own people."""
    return parse_person_expression(expression).evaluate(
        lambda person: (item.id for item in pool if person in {p.id for p in item.people})
    )


def test_copies_of_one_item_pool_their_people_so_an_and_holds_on_it() -> None:
    """Each account tagged its own copy; the item is the picture, so both tags count."""
    bytes_ = _sha1("both-kids.jpg")

    folded = fold_exact_copies(
        (
            _photo("mine", owner="owner-a", checksum=bytes_, people=("kid-1",)),
            _photo("theirs", owner="owner-b", checksum=bytes_, people=("kid-2", "kid-1")),
        ),
        primary_owner_id="owner-a",
    )

    [item] = folded.pool
    assert [person.id for person in item.people] == ["kid-1", "kid-2"]
    assert _holding(folded.pool, '"kid-1" and "kid-2"') == {"mine"}


def test_two_different_photos_never_satisfy_an_and_together() -> None:
    folded = fold_exact_copies(
        (
            _photo("kid-1-alone", checksum=_sha1("one"), people=("kid-1",)),
            _photo("kid-2-alone", checksum=_sha1("two"), people=("kid-2",)),
        ),
        primary_owner_id=None,
    )

    assert _holding(folded.pool, '"kid-1" and "kid-2"') == frozenset()
    assert _holding(folded.pool, '"kid-1" or "kid-2"') == {"kid-1-alone", "kid-2-alone"}


def test_a_live_photo_keeps_its_own_motion_and_the_absorbed_motion_leaves_with_its_still() -> None:
    """Equal stills do not prove equal motion: no copy plays another copy's companion."""
    bytes_ = _sha1("live-still.heic")
    kept_motion = _photo("motion-z", kind=AssetType.VIDEO, checksum=_sha1("motion one"))
    absorbed_motion = _photo("motion-a", kind=AssetType.VIDEO, checksum=_sha1("motion two"))

    folded = fold_exact_copies(
        (
            _photo("still-a", checksum=bytes_, companion="motion-a"),
            absorbed_motion,
            _photo("still-z", checksum=bytes_, companion="motion-z", favourite=True),
            kept_motion,
        ),
        primary_owner_id=None,
    )

    assert _ids(folded.pool) == ["motion-z", "still-z"]
    assert folded.pool[1].live_photo_video_id == "motion-z"
    [group] = folded.groups
    assert {(ref.asset_id, ref.companion_id) for ref in group.references} == {
        ("still-z", "motion-z"),
        ("still-a", "motion-a"),
    }


def test_a_plain_photo_kept_over_a_live_copy_gains_no_motion() -> None:
    bytes_ = _sha1("still.heic")

    folded = fold_exact_copies(
        (
            _photo("plain", checksum=bytes_, favourite=True),
            _photo("live", checksum=bytes_, companion="motion"),
            _photo("motion", kind=AssetType.VIDEO, checksum=_sha1("motion")),
        ),
        primary_owner_id=None,
    )

    assert _ids(folded.pool) == ["plain"]
    assert folded.pool[0].live_photo_video_id is None


def test_the_editorial_pool_admits_one_copy_and_keeps_the_group_for_the_record() -> None:
    bytes_ = _sha1("shared.heic")
    request = EditorialSelectionRequest(scope=SourceScope(), primary_owner_id="owner-b")
    pages = (
        _photo("a-copy", owner="owner-a", checksum=bytes_, companion="a-motion"),
        _photo("a-motion", kind=AssetType.VIDEO, checksum=_sha1("a-motion")),
        _photo("b-copy", owner="owner-b", checksum=bytes_),
        _photo("other", checksum=_sha1("other")),
    )

    prepared = prepare_editorial_source(
        request, EditorialDependencies(source_fetcher=lambda _scope: pages)
    )

    assert prepared.candidate_ids == ("b-copy", "other")


def test_an_owner_choice_on_either_copy_holds_for_the_picture() -> None:
    """A tick or an exclusion set on the absorbed copy lands on the copy that is kept."""
    shared, excluded_shared = _sha1("shared.heic"), _sha1("excluded.heic")
    pages = (
        _photo("a-copy", owner="owner-a", checksum=shared),
        _photo("b-copy", owner="owner-b", checksum=shared),
        _photo("a-gone", owner="owner-a", checksum=excluded_shared),
        _photo("b-gone", owner="owner-b", checksum=excluded_shared),
    )
    request = EditorialSelectionRequest(
        scope=SourceScope(),
        owner_required_asset_ids=("a-copy",),
        owner_excluded_asset_ids=("a-gone",),
        primary_owner_id="owner-b",
    )

    prepared = prepare_editorial_source(
        request, EditorialDependencies(source_fetcher=lambda _scope: pages)
    )

    assert prepared.candidate_ids == ("b-copy",)
    assert prepared.owner_required_asset_ids == ("b-copy",)
    assert prepared.excluded_ids == ("b-gone",)


def _live_photo(still_id: str, motion_id: str, *, owner: str, motion: str, **still) -> tuple:
    """A Live Photo as Immich lists it: the still, and its motion half as a hidden video."""
    return (
        _photo(still_id, owner=owner, companion=motion_id, **still),
        _photo(motion_id, owner=owner, kind=AssetType.VIDEO, checksum=_sha1(motion)),
    )


def test_a_video_holding_a_live_photos_own_motion_folds_into_the_live_photo() -> None:
    """The other account saved the motion as a plain video: the moment is the Live Photo."""
    folded = fold_exact_copies(
        (
            *_live_photo(
                "still-a", "motion-a", owner="owner-a", motion="wave", checksum=_sha1("s")
            ),
            _photo("video-b", owner="owner-b", kind=AssetType.VIDEO, checksum=_sha1("wave")),
        ),
        primary_owner_id="owner-b",
    )

    assert _ids(folded.pool) == ["motion-a", "still-a"]
    assert folded.pool[1].live_photo_video_id == "motion-a"
    [group] = folded.groups
    assert group.representative_id == "still-a"
    assert {reference.asset_id for reference in group.references} == {"still-a", "video-b"}


def _video(asset_id: str, owner: str, content: str, *, favourite: bool = False) -> Asset:
    return _photo(
        asset_id, owner=owner, kind=AssetType.VIDEO, checksum=_sha1(content), favourite=favourite
    )


def _shared_live_photo(**b_still) -> tuple:
    """Both accounts hold one Live Photo; each account's motion half is its own file."""
    still = _sha1("still.heic")
    return (
        *_live_photo("still-a", "motion-a", owner="owner-a", motion="a", checksum=still),
        *_live_photo("still-b", "motion-b", owner="owner-b", motion="b", checksum=still, **b_still),
    )


def test_a_video_holding_the_motion_of_the_absorbed_still_folds_too() -> None:
    """The absorbed still takes its motion with it; a video equal to that motion goes as well."""
    folded = fold_exact_copies(
        (*_shared_live_photo(), _video("video-c", "owner-c", "b")), primary_owner_id="owner-a"
    )

    assert _ids(folded.pool) == ["motion-a", "still-a"]
    assert folded.pool[1].live_photo_video_id == "motion-a"
    [group] = folded.groups
    assert {ref.asset_id for ref in group.references} == {"still-a", "still-b", "video-c"}


def test_a_star_on_the_other_accounts_motion_half_stars_the_kept_picture() -> None:
    *pool, motion_b = _shared_live_photo()
    starred_motion = motion_b.model_copy(update={"is_favorite": True})

    folded = fold_exact_copies((*pool, starred_motion), primary_owner_id="owner-a")

    assert _ids(folded.pool) == ["motion-a", "still-a"]
    assert folded.pool[1].is_favorite


def test_a_star_on_the_standalone_video_stars_the_kept_live_photo() -> None:
    folded = fold_exact_copies(
        (
            *_live_photo("still-a", "motion-a", owner="owner-a", motion="wave"),
            _video("video-b", "owner-b", "wave", favourite=True),
        ),
        primary_owner_id="owner-b",
    )

    assert _ids(folded.pool) == ["motion-a", "still-a"]
    assert folded.pool[1].is_favorite


def test_an_owner_tick_on_the_standalone_video_holds_for_the_live_photo() -> None:
    pages = (
        *_live_photo("still-a", "motion-a", owner="owner-a", motion="wave"),
        _video("video-b", "owner-b", "wave"),
    )
    request = EditorialSelectionRequest(
        scope=SourceScope(), owner_required_asset_ids=("video-b",), primary_owner_id="owner-b"
    )

    prepared = prepare_editorial_source(
        request, EditorialDependencies(source_fetcher=lambda _scope: pages)
    )

    assert prepared.candidate_ids == ("still-a",)
    assert prepared.owner_required_asset_ids == ("still-a",)


def test_videos_matching_no_live_photo_motion_fold_only_with_each_other() -> None:
    folded = fold_exact_copies(
        (
            *_live_photo("still-a", "motion-a", owner="owner-a", motion="wave"),
            _video("video-b", "owner-b", "clip"),
            _video("video-c", "owner-c", "clip"),
            _video("video-d", "owner-d", "other"),
        ),
        primary_owner_id=None,
    )

    assert _ids(folded.pool) == ["motion-a", "still-a", "video-b", "video-d"]
    [group] = folded.groups
    assert group.representative_id == "video-b"


def test_reversed_order_folds_motion_copies_the_same_way() -> None:
    pages = (
        *_shared_live_photo(favourite=True),
        _video("video-c", "owner-c", "a"),
        _video("video-d", "owner-d", "b", favourite=True),
    )

    forward = fold_exact_copies(pages, primary_owner_id="owner-a")
    backward = fold_exact_copies(pages[::-1], primary_owner_id="owner-a")

    assert forward == backward
    assert _ids(forward.pool) == ["motion-b", "still-b"]
    [group] = forward.groups
    assert {ref.asset_id for ref in group.references} == {
        "still-a",
        "still-b",
        "video-c",
        "video-d",
    }


def test_the_kept_copy_is_opened_through_the_account_that_holds_it() -> None:
    bytes_ = _sha1("garden.jpg")
    primary_copy = _photo("p-copy", owner="owner-p", checksum=bytes_).model_copy(
        update={"access_accounts": ("primary",)}
    )
    partner_copy = _photo("w-copy", owner="owner-w", checksum=bytes_, favourite=True).model_copy(
        update={"access_accounts": ("partner",)}
    )

    folded = fold_exact_copies((primary_copy, partner_copy), primary_owner_id="owner-p")

    assert _ids(folded.pool) == ["w-copy"]
    assert folded.pool[0].access_accounts == ("partner",)
