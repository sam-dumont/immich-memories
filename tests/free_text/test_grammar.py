"""Caption grammar: what a caption is about, read without a model."""

from __future__ import annotations

from dataclasses import dataclass

from immich_memories.free_text.grammar import free_tier, is_about, is_thing
from immich_memories.free_text.lexicon import Lexicon


def test_the_subject_ends_at_the_first_verb() -> None:
    assert is_about("A black cat is sleeping on a sofa", ["cat"])
    assert not is_about("A man holding a cat in a garden", ["cat"])


def test_a_phrase_needs_every_word_in_the_subject_and_its_last_word_as_the_head() -> None:
    assert is_about("A black cat is sleeping on a sofa", ["black cat"])
    assert not is_about("A white cat is sleeping on a sofa", ["black cat"])
    assert not is_about("A car seat in the back of a van", ["car"])


def test_a_group_of_and_a_screenshot_of_read_through_to_what_they_hold() -> None:
    assert is_about("A group of cyclists riding along a coastal road", ["cyclist"])
    assert is_about("A screenshot of a fitness app showing a route", ["app"])
    assert not is_about("A slice of bread on a plate", ["bread"])


def test_trailing_participles_and_particles_leave_the_subject() -> None:
    assert is_about("A black cat curled up on a bed", ["cat"])
    assert is_about("A small dog happily running across a field", ["dog"])


def test_a_possessive_keeps_its_owner_in_the_subject() -> None:
    assert is_about("A car's dashboard with a speedometer", ["car"])
    assert is_about("A car's dashboard with a speedometer", ["dashboard"])
    assert not is_about("A car's dashboard with a speedometer", ["speedometer"])


def test_an_exclusion_that_names_the_subject_rules_the_caption_out() -> None:
    assert is_about("A red toy car on a rug", ["car"])
    assert not is_about("A red toy car on a rug", ["car"], excluded=["toy cars"])
    assert is_about("A red car parked by a toy shop", ["car"], excluded=["toy cars"])


def test_a_thing_is_decided_by_the_head_words_first_wordnet_sense(lexicon: Lexicon) -> None:
    assert is_thing("our black cats", lexicon)
    assert not is_thing("the park", lexicon)
    assert is_thing("sport app", lexicon)


@dataclass(frozen=True)
class Picture:
    name: str
    caption: str | None


def _names(pictures: list[Picture]) -> set[str]:
    return {picture.name for picture in pictures}


def test_the_free_tier_keeps_pictures_whose_caption_is_about_a_thing(lexicon: Lexicon) -> None:
    pool = [
        Picture("asleep", "A black cat is sleeping on a sofa"),
        Picture("held", "A man holding a cat in a garden"),
        Picture("unread", None),
    ]

    assert _names(free_tier(pool, ["cat"], lexicon)) == {"asleep"}


def test_a_place_or_an_event_counts_anywhere_in_the_caption_in_either_order(
    lexicon: Lexicon,
) -> None:
    pool = [
        Picture("kids", "Two children playing on a slide in a park"),
        Picture("track", "Cars lined up for a race on a wet track"),
        Picture("street", "A car parked on a quiet street"),
    ]

    assert _names(free_tier(pool, ["park"], lexicon)) == {"kids"}
    assert _names(free_tier(pool, ["car race"], lexicon)) == {"track"}


def test_an_excluded_phrase_anywhere_in_a_scene_caption_rules_it_out(lexicon: Lexicon) -> None:
    pool = [
        Picture("runners", "Runners crossing the finish line at a race"),
        Picture("floor", "Toy cars lined up for a race on a kitchen floor"),
    ]

    assert _names(free_tier(pool, ["race"], lexicon, excluded=["toy cars"])) == {"runners"}


def test_no_subject_words_leave_every_captioned_picture(lexicon: Lexicon) -> None:
    pool = [Picture("read", "A woman smiling at a table"), Picture("unread", None)]

    assert _names(free_tier(pool, [], lexicon)) == {"read"}
