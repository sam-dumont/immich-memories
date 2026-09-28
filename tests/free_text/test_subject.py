"""The subject: what the photos show, read from the request's what-spans by grammar and WordNet."""

from __future__ import annotations

from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPerson
from immich_memories.free_text.linking import Household
from immich_memories.free_text.reading import Reading
from immich_memories.free_text.subject import subject_words

NOBODY = Household({})


def _reading(request: str, *, who: tuple[str, ...] = (), what: tuple[str, ...] = ()) -> Reading:
    return Reading(request=request, who=who, what=what)


def test_the_head_noun_of_each_coordinated_part_skipping_words_for_the_picture(
    lexicon: Lexicon,
) -> None:
    cat = subject_words(
        _reading("pictures of our cat", what=("pictures of our cat",)), NOBODY, lexicon
    )
    both = subject_words(
        _reading("beaches and pools", what=("beaches and pools",)), NOBODY, lexicon
    )

    assert cat.heads == ("cat",)
    assert both.heads == ("beaches", "pools")


def test_people_and_a_trailing_time_phrase_are_never_the_subject(lexicon: Lexicon) -> None:
    rose = LibraryPerson("p-rose", "Rose Example", "daughter", None)
    household = Household({"p-rose": rose})

    eyes = subject_words(
        _reading("closed eyes along the years", what=("closed eyes along the years",)),
        household,
        lexicon,
    )
    friends = subject_words(
        _reading("the beach with friends", who=("friends",), what=("the beach with friends",)),
        household,
        lexicon,
    )
    named = subject_words(
        _reading("rose and the dog", what=("rose and the dog",)), household, lexicon
    )

    assert eyes.heads == ("eyes",)
    assert friends.heads == ("beach",)
    assert named.heads == ("dog",)


def test_an_activity_adds_the_nouns_wordnet_forms_from_it(lexicon: Lexicon) -> None:
    hiking = subject_words(
        _reading("me hiking along the years", who=("me",), what=("hiking",)), NOBODY, lexicon
    )
    partying = subject_words(_reading("partying", what=("partying",)), NOBODY, lexicon)

    assert hiking.heads == ("hiking",)
    assert hiking.words == ("hiking", "hike", "hiker")
    assert partying.heads == ("partying",)
    assert "party" in partying.words


def test_the_thing_made_is_the_subject_of_its_making(lexicon: Lexicon) -> None:
    bread = subject_words(
        _reading("bread making along the years", what=("bread making",)), NOBODY, lexicon
    )

    assert (bread.heads, bread.words) == (("bread",), ("bread",))
