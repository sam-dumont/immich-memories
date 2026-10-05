"""A stack of an edit and its original ships only the primary (immich-app/immich#31082)."""

from __future__ import annotations

from immich_memories.analysis.stacks import fold_stacks, stack_reason, starred_primaries
from tests.conftest import make_asset


def test_a_stack_member_folds_into_its_primary_regardless_of_pixels():
    # The edit is the stack primary (assetIds[0] on Immich's mobile auto-stack) and has
    # fewer pixels than the original it came from; the stack decides, not the pixel count.
    edit = make_asset("edit", original_file_name="IMG_1234_edit.heic")
    edit.width, edit.height = 1000, 1000
    original = make_asset("original", original_file_name="IMG_1234.heic")
    original.width, original.height = 4000, 3000

    folded = fold_stacks([edit, original], {"original": "edit"})

    assert folded == {"original": edit}


def test_the_primary_is_never_folded_into_itself():
    edit = make_asset("edit")
    original = make_asset("original")

    folded = fold_stacks([edit, original], {"original": "edit", "edit": "edit"})

    assert folded == {"original": edit}


def test_a_burst_stack_folds_every_member_into_its_primary():
    primary = make_asset("primary")
    second = make_asset("second")
    third = make_asset("third")

    folded = fold_stacks([primary, second, third], {"second": "primary", "third": "primary"})

    assert folded == {"second": primary, "third": primary}


def test_a_favourite_on_any_member_moves_to_the_primary():
    edit = make_asset("edit", is_favorite=False)
    original = make_asset("original", is_favorite=True)

    folded = fold_stacks([edit, original], {"original": "edit"})

    assert starred_primaries(folded, [edit, original]) == {"edit"}


def test_a_member_whose_primary_never_reached_this_pool_is_left_alone():
    original = make_asset("original")

    assert fold_stacks([original], {"original": "a-primary-not-in-the-pool"}) == {}


def test_stack_reason_names_the_primary_file():
    primary = make_asset("primary", original_file_name="IMG_1234.heic")

    assert "IMG_1234.heic" in stack_reason(primary)
