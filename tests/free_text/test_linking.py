"""Linking a reading to the library by code: people, dates, places, each with its reason."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from immich_memories.free_text.homes import Home
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPerson
from immich_memories.free_text.linking import (
    Household,
    WhoLink,
    link_when,
    link_where,
    link_who,
    time_cut,
)
from tests.free_text.banked import BankedAsker

OWNER = LibraryPerson("p-owner", "Ada Example", None, date(1990, 6, 15))
PARTNER = LibraryPerson("p-partner", "Bo Example", "partner", date(1991, 2, 1))
SON = LibraryPerson("p-son", "Cy Example", "son", date(2020, 3, 10))
FRIEND = LibraryPerson("p-friend", "Di Sample", "friend", None)
PEOPLE = {person.person_id: person for person in (OWNER, PARTNER, SON, FRIEND)}
HOUSEHOLD = Household(PEOPLE, "p-owner")
STRANGERS = Household(PEOPLE)


def _unasked() -> BankedAsker:
    # WHY: stands in for the model server; an empty bank fails any question asked.
    return BankedAsker()


def test_i_is_the_owner_for_dates_and_homes_never_a_face(lexicon: Lexicon) -> None:
    who = link_who("the cars I drove", ("i",), HOUSEHOLD, lexicon, _unasked())

    assert who.anchors == ("p-owner",)
    assert who.present == ()
    assert who.company is None
    assert "no face" in who.reasons[0].rule


def test_we_is_the_owner_and_the_partner_by_role(lexicon: Lexicon) -> None:
    wife = LibraryPerson("p-wife", "Eve Example", "wife", None)
    people = {"p-owner": OWNER, "p-wife": wife, "p-son": SON}

    who = link_who("our wedding", (), Household(people, "p-owner"), lexicon, _unasked())

    assert who.anchors == ("p-owner", "p-wife")
    assert who.present == ()


def test_a_role_or_a_name_requires_that_persons_face(lexicon: Lexicon) -> None:
    by_role = link_who("my son at the beach", ("my son",), HOUSEHOLD, lexicon, _unasked())
    by_name = link_who("Di and me", ("di",), HOUSEHOLD, lexicon, _unasked())

    assert by_role.present == ("p-son",)
    assert by_name.present == ("p-friend",)
    assert by_role.anchors == ("p-owner", "p-son")
    assert "faces required" in by_role.reasons[-1].rule


def test_a_plural_word_for_people_asks_for_company(lexicon: Lexicon) -> None:
    friends = link_who("me and friends", ("me", "friends"), HOUSEHOLD, lexicon, _unasked())
    kids = link_who("at the park with kids", ("kids",), STRANGERS, lexicon, _unasked())
    cars = link_who("the cars", ("the cars",), STRANGERS, lexicon, _unasked())

    assert (friends.company, friends.present) == ("people", ())
    assert kids.company == "children"
    assert cars == link_who("", (), STRANGERS, lexicon, _unasked())
    assert friends.absent_company is None and friends.company_only is False


def test_a_negation_asks_the_company_be_absent_not_required(lexicon: Lexicon) -> None:
    # #2061: "no humans"/"without children" must not make that company required.
    no_humans = link_who("paysages, no humans", ("no humans",), STRANGERS, lexicon, _unasked())
    without_kids = link_who(
        "without children", ("without children",), STRANGERS, lexicon, _unasked()
    )

    assert (no_humans.absent_company, no_humans.company) == ("people", None)
    assert (without_kids.absent_company, without_kids.company) == ("children", None)
    assert "ABSENT" in no_humans.reasons[0].outcome


def test_real_wordnet_no_injected_vocab_still_reads_no_humans_as_absent() -> None:
    """#2061: the actual bug was `noun_base("humans")` staying "humans" on the real corpus
    (an irregular plural WordNet's morphy does not reduce), so the old WordNet-dependent
    path never classified it. Company words are now a curated list independent of
    WordNet, read against the real pinned corpus, with no word injected for this test."""
    import pwd

    from immich_memories.free_text.lexicon import WordNetUnavailable, load_wordnet

    # The real account's home, not the disposable one the unit suite seals HOME to
    # (tests/conftest.py `_leave_the_accounts_home`): a read-only pinned corpus, never a
    # store, so reading it here carries none of the mutation risk that seal guards against.
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    path = real_home / ".immich-memories" / "models" / "wordnet" / "wordnet.zip"
    try:
        real_lexicon = load_wordnet(path)
    except WordNetUnavailable:
        pytest.skip("the real pinned WordNet corpus is not installed (`models fetch`)")

    assert real_lexicon.noun_base("humans") == "humans"  # confirms the bug would still exist
    assert real_lexicon.is_human("humans") is False  # if anything here still asked WordNet

    who = link_who("landscapes, no humans", ("no humans",), STRANGERS, real_lexicon, _unasked())

    assert (who.absent_company, who.company) == ("people", None)


_NO_PEOPLE_BY_LOCALE = {
    "en": ("landscapes, no humans", "people"),
    "fr": ("paysages, sans humains", "people"),
    "nl": ("landschappen zonder mensen", "people"),
    "de": ("Landschaften ohne Menschen", "people"),
    "es": ("paisajes sin personas", "people"),
    "it": ("paesaggi senza persone", "people"),
    "pt-BR": ("paisagens sem pessoas", "people"),
    "pt-PT": ("paisagens sem pessoas", "people"),
    "pl": ("krajobrazy bez ludzi", "people"),
    "sv": ("landskap utan människor", "people"),
    "ru": ("пейзажи без людей", "people"),
    "ja": ("風景、人間なし", "people"),
    "ko": ("풍경, 사람들 없이", "people"),
    "zh-Hans": ("风景，没有人们", "people"),
}


@pytest.mark.parametrize("locale", sorted(_NO_PEOPLE_BY_LOCALE))
def test_negation_is_read_in_every_supported_locale(locale: str, lexicon: Lexicon) -> None:
    """One natural "no people in the landscape" request per locale in
    `immich_memories.i18n.SUPPORTED_LOCALES` (#2061)."""
    request, kind = _NO_PEOPLE_BY_LOCALE[locale]
    who = link_who(request, (request,), STRANGERS, lexicon, _unasked())

    assert who.absent_company == kind
    assert who.company is None


def test_only_a_specific_company_kind_stays_specific_not_generic_people(lexicon: Lexicon) -> None:
    # #2061: "only the performers" must not collapse to generic "people".
    english = link_who(
        "live music, only the performers", ("only the performers",), STRANGERS, lexicon, _unasked()
    )
    french = link_who(
        "seulement les musiciens en concert",
        ("seulement les musiciens",),
        STRANGERS,
        lexicon,
        _unasked(),
    )

    assert (english.company, english.company_only) == ("performers", True)
    assert (french.company, french.company_only) == ("performers", True)


def test_mixed_clauses_do_not_let_one_negation_invert_another(lexicon: Lexicon) -> None:
    with_kids_no_rain = link_who(
        "avec les enfants, pas de pluie",
        ("avec les enfants", "pas de pluie"),
        STRANGERS,
        lexicon,
        _unasked(),
    )
    kids_not_teens = link_who(
        "les enfants mais pas les ados",
        ("les enfants mais pas les ados",),
        STRANGERS,
        lexicon,
        _unasked(),
    )
    band_no_crowd = link_who(
        "only the band and no crowd",
        ("only the band and no crowd",),
        STRANGERS,
        lexicon,
        _unasked(),
    )
    kids_absent_friends_required = link_who(
        "sans les enfants avec des amis",
        ("sans les enfants avec des amis",),
        STRANGERS,
        lexicon,
        _unasked(),
    )

    assert (with_kids_no_rain.company, with_kids_no_rain.absent_company) == ("children", None)
    assert (kids_not_teens.company, kids_not_teens.absent_company) == ("children", "teens")
    assert (band_no_crowd.company, band_no_crowd.absent_company) == ("performers", "audience")
    assert band_no_crowd.company_only is True
    assert (kids_absent_friends_required.company, kids_absent_friends_required.absent_company) == (
        "people",
        "children",
    )


def test_a_named_person_negated_is_excluded_not_required(lexicon: Lexicon) -> None:
    excluded = link_who("without Cy", ("without cy",), HOUSEHOLD, lexicon, _unasked())
    double_negative = link_who(
        "not without the kids", ("not without the kids",), STRANGERS, lexicon, _unasked()
    )

    assert excluded.present == ()
    assert excluded.absent_present == ("p-son",)
    assert double_negative.company == "children"
    assert double_negative.absent_company is None


def test_personne_negates_itself_in_ne_y_a_personne(lexicon: Lexicon) -> None:
    # French's own bipartite negation: "personne" alone already means "nobody".
    who = link_who("il n'y a personne", ("il n'y a personne",), STRANGERS, lexicon, _unasked())

    assert who.absent_company == "people"
    assert who.company is None


def test_elided_articles_split_from_their_word(lexicon: Lexicon) -> None:
    who = link_who("pas d'enfants", ("pas d'enfants",), STRANGERS, lexicon, _unasked())

    assert who.absent_company == "children"


def test_negation_the_reader_puts_in_what_or_drops_is_still_read(lexicon: Lexicon) -> None:
    """#2061 round 3: six locales were lost on real data because a real reader puts a
    negated company phrase in `what`, or drops it from every span entirely. Negation and
    company are read over the whole request too, not only the `who` spans the model gave."""
    in_what = link_who("landschappen zonder mensen", (), STRANGERS, lexicon, _unasked())
    dropped = link_who("без людей", (), STRANGERS, lexicon, _unasked())

    assert in_what.absent_company == "people"
    assert dropped.absent_company == "people"


def test_a_whole_text_scan_never_overrides_a_more_specific_who_span(lexicon: Lexicon) -> None:
    # The who span already says "children" required; the fallback whole-text scan must not
    # also read "no rain" elsewhere in the request as anything about company.
    who = link_who(
        "with the kids, no rain please", ("with the kids",), STRANGERS, lexicon, _unasked()
    )

    assert (who.company, who.absent_company) == ("children", None)


def test_negation_scopes_forward_not_back_over_the_company_word(lexicon: Lexicon) -> None:
    # #2061: "kids not wearing hats" must keep the kids; "not" negates what follows it.
    who = link_who(
        "kids not wearing hats", ("kids not wearing hats",), STRANGERS, lexicon, _unasked()
    )

    assert (who.company, who.absent_company) == ("children", None)


def test_except_and_excluding_mean_absent(lexicon: Lexicon) -> None:
    except_kids = link_who("except the kids", ("except the kids",), STRANGERS, lexicon, _unasked())
    excluding = link_who(
        "excluding children", ("excluding children",), STRANGERS, lexicon, _unasked()
    )
    french = link_who("sauf les enfants", ("sauf les enfants",), STRANGERS, lexicon, _unasked())

    assert except_kids.absent_company == "children"
    assert excluding.absent_company == "children"
    assert french.absent_company == "children"


def test_sans_personne_does_not_cancel_back_to_required(lexicon: Lexicon) -> None:
    # #2061: two negation words in the same clause are not two negations that cancel; an
    # absolute negative pronoun ("personne") is always absence, on its own.
    who = link_who("sans personne", ("sans personne",), STRANGERS, lexicon, _unasked())

    assert (who.absent_company, who.company) == ("people", None)


_HELD_OUT = {
    # Owner ruling round 3: 15+ requests not designed into the code, spread across locales,
    # to check the mechanism generalises rather than matching two campaign phrases. The
    # reader rarely segments a who-span cleanly, so these go through an empty `who` to
    # exercise the hardest path: company and negation read over the whole request alone.
    "le marche de noel, sans la foule": ("absent", "audience"),  # fr: without the crowd
    "beach without strangers": ("absent", "people"),  # en
    "nur die kinder beim spielen": ("required", "children"),  # de: only the children playing
    "het strand zonder mensen": ("absent", "people"),  # nl: the beach without people
    "tylko dzieci": ("required", "children"),  # pl: only children
    "solo i bambini": ("required", "children"),  # it: only the children
    "apenas as criancas": ("required", "children"),  # pt-BR: only the children
    "food, no faces": ("absent", "people"),  # en: a face stands for the person
    "sin extranos": ("absent", "people"),  # es: without strangers
    # Correct non-matches: the subject is not people at all, so neither slot should fire,
    # even though each one carries a real negation or "only" marker of its own.
    "solo los perros": (None, None),  # es: only the dogs
    "zonder auto's": (None, None),  # nl: without cars
    "bez psow": (None, None),  # pl: without dogs
    "nothing but sunsets": (None, None),  # en
    "the wedding, no kissing": (None, None),  # en
    "только море": (None, None),  # ru: only the sea
}


@pytest.mark.parametrize("request_text", sorted(_HELD_OUT))
def test_held_out_requests_generalise_beyond_the_two_campaign_phrases(
    request_text: str, lexicon: Lexicon
) -> None:
    """15+ requests this fix was never designed around (owner ruling, round 3): the reader
    put nothing useful in `who`, so this is the hardest path -- company and negation read
    over the whole request text alone."""
    slot, kind = _HELD_OUT[request_text]
    who = link_who(request_text, (), STRANGERS, lexicon, _unasked())

    if slot is None:
        assert (who.company, who.absent_company) == (None, None)
    elif slot == "required":
        assert who.company == kind
    else:
        assert who.absent_company == kind


def test_cjk_held_out_requests_generalise(lexicon: Lexicon) -> None:
    ja_snow = link_who("雪の日、人なし", (), STRANGERS, lexicon, _unasked())
    ko_only = link_who("아이들만", (), STRANGERS, lexicon, _unasked())

    assert ja_snow.absent_company == "people"
    assert (ko_only.company, ko_only.company_only) == ("children", True)


@pytest.mark.xfail(
    reason=(
        "#2061 round 3, known gap: 'grandpa' and 'everyone' both fold to the same generic "
        "'people' kind, so a required and an absent slot collide on one word instead of "
        "reading as 'everyone, but not grandpa'. Needs a finer kind than this table has."
    ),
    strict=True,
)
def test_everyone_except_a_specific_person_is_a_known_gap(lexicon: Lexicon) -> None:
    who = link_who("everyone except grandpa", (), STRANGERS, lexicon, _unasked())

    assert (who.company, who.absent_company) == ("people", None)


def test_cjk_negation_reads_an_inflected_natural_phrase(lexicon: Lexicon) -> None:
    ja = link_who("人のいない風景", ("人のいない風景",), STRANGERS, lexicon, _unasked())
    ko = link_who("사람 없는 풍경", ("사람 없는 풍경",), STRANGERS, lexicon, _unasked())
    zh = link_who("风景，没有人们", ("没有人们",), STRANGERS, lexicon, _unasked())

    assert ja.absent_company == "people"
    assert ko.absent_company == "people"
    assert zh.absent_company == "people"


def test_absolute_negative_pronouns_mean_absent_people(lexicon: Lexicon) -> None:
    nobody = link_who("nobody here", ("nobody here",), STRANGERS, lexicon, _unasked())
    strangers = link_who("no strangers", ("no strangers",), STRANGERS, lexicon, _unasked())
    tourists = link_who("no tourists", ("no tourists",), STRANGERS, lexicon, _unasked())
    german = link_who("niemand", ("niemand",), STRANGERS, lexicon, _unasked())

    assert nobody.absent_company == "people"
    assert strangers.absent_company == "people"
    assert tourists.absent_company == "people"
    assert german.absent_company == "people"


def test_a_first_name_two_people_share_is_picked_by_vote(lexicon: Lexicon) -> None:
    cousin = LibraryPerson("p-cousin", "Cy Other", "cousin", None)
    people = {**PEOPLE, "p-cousin": cousin}

    cousin_vote = {"reason": "", "choice": "Cy Other (cousin)"}
    # WHY: stands in for the model server; two of three answers pick the cousin.
    asker = BankedAsker(cousin_vote, {"reason": "", "choice": "Cy Example (son)"}, cousin_vote)

    who = link_who("Cy at the beach", ("cy",), Household(people, "p-owner"), lexicon, asker)

    assert who.present == ("p-cousin",)
    assert "2/3" in who.reasons[-1].rule


TODAY = date(2026, 1, 1)
OWNER_ONLY = WhoLink(anchors=("p-owner",))


def test_an_age_is_read_as_numbers_and_the_calendar_is_code() -> None:
    # WHY: stands in for the model server; one anchor means one question.
    asker = BankedAsker(
        {"reason": "", "is_age": True, "whose_age": "Ada Example", "age_from": 20, "age_to": 29}
    )

    when = link_when(
        "me and friends partying in our 20s",
        ("in our 20s",),
        OWNER_ONLY,
        HOUSEHOLD,
        asker,
        today=TODAY,
    )

    assert (when.start, when.end) == (date(2010, 6, 15), date(2020, 6, 14))
    assert "born 1990-06-15" in when.reasons[0].rule


def test_time_words_that_are_no_age_are_dated_by_the_model_from_the_facts() -> None:
    not_an_age = {
        "reason": "",
        "is_age": False,
        "whose_age": "Ada Example",
        "age_from": 0,
        "age_to": 0,
    }
    # WHY: stands in for the model server; the age gate says no, then the dates are banked.
    asker = BankedAsker(not_an_age, {"date_from": "2016-03-01", "date_to": None})

    when = link_when(
        "our house since we moved in",
        ("since we moved in",),
        OWNER_ONLY,
        HOUSEHOLD,
        asker,
        today=TODAY,
    )

    assert (when.start, when.end) == (date(2016, 3, 1), None)
    dates_question = asker.questions[1][0]
    assert '"today": "2026-01-01"' in dates_question


def test_nothing_said_about_time_asks_nothing_and_is_any_time() -> None:
    when = link_when("our cat", (), OWNER_ONLY, HOUSEHOLD, _unasked(), today=TODAY)

    assert (when.start, when.end) == (None, None)
    assert when.reasons[0].outcome == "any time"


def test_years_written_in_the_request_are_found_by_pattern_and_dated() -> None:
    # WHY: stands in for the model server; a valid-shaped but impossible day is read as no bound.
    asker = BankedAsker({"date_from": "2014-01-01", "date_to": "2024-02-30"})

    when = link_when("black cat 2014-2024", (), WhoLink(), HOUSEHOLD, asker, today=TODAY)

    assert (when.start, when.end) == (date(2014, 1, 1), None)
    assert '"years_in_request": ["2014", "2024"]' in asker.questions[0][0]


def test_an_age_stands_when_both_orders_of_two_people_read_it_alike() -> None:
    two = WhoLink(anchors=("p-owner", "p-son"))
    son_at_two = {
        "reason": "",
        "is_age": True,
        "whose_age": "Cy Example",
        "age_from": 2,
        "age_to": 2,
    }
    owner_at_two = {**son_at_two, "whose_age": "Ada Example"}
    # WHY: stands in for the model server; two people give two orders of asking.
    agreed = BankedAsker(son_at_two, son_at_two)
    # WHY: as above; the orders disagree, so the dates question is asked instead.
    split = BankedAsker(son_at_two, owner_at_two, {"date_from": None, "date_to": None})

    when = link_when("my son at two", ("at two",), two, HOUSEHOLD, agreed, today=TODAY)
    unsure = link_when("my son at two", ("at two",), two, HOUSEHOLD, split, today=TODAY)

    assert (when.start, when.end) == (date(2022, 3, 10), date(2023, 3, 9))
    assert (unsure.start, unsure.end) == (None, None)


def test_a_trailing_time_phrase_is_cut_from_the_subject_side(lexicon: Lexicon) -> None:
    assert time_cut("closed eyes along the years", lexicon) == "closed eyes"
    assert time_cut("kids in the park over the years", lexicon) == "kids in the park"
    assert time_cut("cars in the park", lexicon) == "cars in the park"


FIRST_HOME = Home(50.0, 4.0, since=None, until=date(2016, 3, 1))
SECOND_HOME = Home(50.1, 4.1, since=date(2016, 3, 1), until=None)
AT_HOMES = Household(PEOPLE, "p-owner", (FIRST_HOME, SECOND_HOME))


def _picks(scope_words: str) -> dict[str, Any]:
    return {"reason": "", "choice": scope_words}


def _option(schema: Mapping[str, Any], starts: str) -> str:
    return next(o for o in schema["properties"]["choice"]["enum"] if o.startswith(starts))


def test_a_place_phrase_is_one_voted_place() -> None:
    def at_home(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "at home, wherever"))

    # WHY: stands in for the model server; three votes for the home of the time.
    asker = BankedAsker(at_home, at_home, at_home)

    where = link_where("our cat at home", ("at home",), {"cat"}, AT_HOMES, asker)

    assert (where.scope, where.home) == ("home_at_time", None)
    assert "3/3" in where.reasons[0].rule


def test_a_place_phrase_of_only_the_subjects_nouns_says_nowhere() -> None:
    beaches = link_where(
        "beaches and pools", ("beaches and pools",), {"beaches", "pools"}, AT_HOMES, _unasked()
    )
    park = link_where("at the park with kids", ("at the park",), {"park"}, AT_HOMES, _unasked())
    silent = link_where("our cat", (), {"cat"}, AT_HOMES, _unasked())

    assert beaches.scope == park.scope == silent.scope == "anywhere"
    assert beaches.reasons[0].rule == "nothing beyond the subject's own nouns"
    assert silent.reasons[0].rule == "no place words"


def test_home_and_away_together_are_anywhere() -> None:
    def at_home(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "at home, wherever"))

    def away(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "away from home"))

    # WHY: stands in for the model server; the first phrase votes home, the second away.
    asker = BankedAsker(at_home, at_home, at_home, away, away, away)

    where = link_where(
        "brunches at home or outside", ("at home", "outside"), {"brunches"}, AT_HOMES, asker
    )

    assert where.scope == "anywhere"


def test_nested_places_give_the_widest_and_one_home_is_that_home() -> None:
    def second_home(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "at the home lived in from 2016"))

    def near(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "near home"))

    # WHY: stands in for the model server; one phrase votes a home, the other its town.
    nested = BankedAsker(second_home, second_home, second_home, near, near, near)
    # WHY: as above; one phrase, three votes for the second home.
    one = BankedAsker(second_home, second_home, second_home)

    widest = link_where("x", ("in the house", "around town"), (), AT_HOMES, nested)
    house = link_where("x", ("in the new house",), (), AT_HOMES, one)

    assert widest.scope == "near_home"
    assert (house.scope, house.home) == ("home", SECOND_HOME)


def test_unreadable_dates_cannot_remove_a_requested_time_filter():
    import pytest

    # WHY: the date reader returned two unreadable replies, not valid null bounds.
    with pytest.raises(ValueError, match="date"):
        link_when(
            "otters in 2030",
            ("2030",),
            WhoLink(),
            Household({}),
            BankedAsker(None, None),
            today=TODAY,
        )
