"""The subject: what the photos show, read from the request's what-spans by grammar and WordNet."""

from __future__ import annotations

from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPerson
from immich_memories.free_text.linking import Household
from immich_memories.free_text.reading import Reading
from immich_memories.free_text.subject import build_subject, subject_words
from tests.free_text.banked import BankedAsker

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


def _picks(*words: str) -> dict[str, object]:
    return {"reason": "", "choices": list(words)}


def test_the_model_votes_the_main_subject_among_the_subject_words(lexicon: Lexicon) -> None:
    reading = _reading("beaches and pools", what=("beaches and pools",))
    # WHY: stands in for the model server; two of three answers pick beaches only.
    asker = BankedAsker(_picks("beaches"), _picks("beaches", "pools"), _picks("beaches"))

    subject = build_subject(reading, NOBODY, (), lexicon, asker)

    assert subject.heads == ("beaches", "pools")
    assert subject.main == ("beaches",)
    assert subject.votes == {"beaches": 3, "pools": 1}
    assert "beaches 3/3" in subject.reasons[-1].rule


def test_nothing_kept_of_the_models_pick_falls_back_to_the_requests_own_words(
    lexicon: Lexicon,
) -> None:
    reading = _reading("beaches and pools", what=("beaches and pools",))
    # WHY: stands in for the model server; no option gets two votes.
    asker = BankedAsker(_picks("beaches"), _picks("pools"), _picks())

    subject = build_subject(reading, NOBODY, (), lexicon, asker)

    assert subject.main == ("beaches", "pools")
    assert "your own subject words" in subject.reasons[-1].outcome


def test_one_subject_word_is_not_put_to_a_vote(lexicon: Lexicon) -> None:
    reading = _reading("pictures of our cat", what=("pictures of our cat",))

    # WHY: stands in for the model server; an empty bank fails any question asked.
    subject = build_subject(reading, NOBODY, (), lexicon, BankedAsker())

    assert subject.main == ("cat",)


def _choice(word: str) -> dict[str, object]:
    return {"reason": "", "choice": word}


def test_its_own_parts_and_kinds_the_captions_use_count_as_the_subject(lexicon: Lexicon) -> None:
    reading = _reading("our house", what=("our house",))
    captions = ("A kitchen with a table", "a kitchen at night", "A cottage", "a cottage by a lake")
    # WHY: stands in for the model server; every answer picks the house.
    asker = BankedAsker(_picks("house"), _picks("house"), _picks("house"))

    subject = build_subject(reading, NOBODY, captions, lexicon, asker)

    assert subject.main == ("house",)
    assert set(subject.extent) == {"kitchen", "cottage"}
    assert subject.relatives == {"kitchen": "part of house", "cottage": "kind of house"}


def test_an_inherited_part_counts_only_for_a_place(lexicon: Lexicon) -> None:
    house = _reading("our house", what=("our house",))
    bicycles = _reading("our bicycles", what=("our bicycles",))
    walls = ("a white wall", "a wall with a clock")
    wheels = ("a wheel in the mud", "a wheel")
    # WHY: stands in for the model server; the main subject, then what kind of subject it is.
    at_home = BankedAsker(*[_picks("house")] * 3, *[_choice("a place")] * 3)
    # WHY: stands in for the model server; the same two questions for the bicycles.
    riding = BankedAsker(*[_picks("bicycles")] * 3, *[_choice("a thing")] * 3)

    place = build_subject(house, NOBODY, walls, lexicon, at_home)
    thing = build_subject(bicycles, NOBODY, wheels, lexicon, riding)

    assert place.kind == "a place"
    assert place.extent == ("wall",)
    assert place.relatives["wall"] == "part of any building (a house is one)"
    assert thing.extent == ()
    assert thing.also == ("wheel",)


def test_a_word_for_people_the_request_does_not_say_is_never_offered(lexicon: Lexicon) -> None:
    reading = _reading("our team", what=("our team",))
    captions = ("a player kicks a ball", "a player on a field")

    # WHY: stands in for the model server; an empty bank fails any question asked.
    subject = build_subject(reading, NOBODY, captions, lexicon, BankedAsker())

    assert subject.main == ("team",)
    assert "player" not in subject.relatives


def test_a_stated_quality_stays_when_it_narrows_and_the_captions_say_it(lexicon: Lexicon) -> None:
    cat = _reading("our cat, black cat", what=("our cat", "black cat"))
    eyes = _reading("closed eyes along the years", what=("closed eyes along the years",))
    cats = ("a black cat asleep", "A black cat on a sofa", "black cat by a window")
    closed = ("a woman with eyes closed", "a baby, eyes closed", "eyes closed in the sun")
    # WHY: stands in for the model server; the quality narrows which ones belong, 3 of 3.
    narrows = [_choice("it narrows which ones belong")] * 3

    black = build_subject(cat, NOBODY, cats, lexicon, BankedAsker(*narrows))
    shut = build_subject(eyes, NOBODY, closed, lexicon, BankedAsker(*narrows))

    assert black.main == ("black cat",)
    assert shut.main == ("closed eyes",)


def test_a_quality_every_one_has_anyway_is_dropped(lexicon: Lexicon) -> None:
    reading = _reading("a lifetime of live concerts", what=("live concerts",))
    captions = ("a live concert", "live concert crowd", "a band at a live concert")
    # WHY: stands in for the model server; every concert the request means is live, 3 of 3.
    asker = BankedAsker(*[_choice("every one the request means has it anyway")] * 3)

    subject = build_subject(reading, NOBODY, captions, lexicon, asker)

    assert subject.main == ("concerts",)
    assert "has it anyway" in subject.reasons[-1].rule


def test_a_quality_the_captions_never_say_or_a_noun_before_the_head_asks_nothing(
    lexicon: Lexicon,
) -> None:
    cat = _reading("black cat", what=("black cat",))
    apps = _reading("sport apps", what=("sport apps",))

    # WHY: stands in for the model server; an empty bank fails any question asked.
    black = build_subject(cat, NOBODY, ("a cat",), lexicon, BankedAsker())
    # WHY: stands in for the model server; an empty bank fails any question asked.
    sport = build_subject(
        apps, NOBODY, ("sport apps", "sport apps", "sport apps"), lexicon, BankedAsker()
    )

    assert black.main == ("cat",)
    assert sport.main == ("apps",)
