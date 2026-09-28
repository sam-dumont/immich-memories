"""Linking a reading to the library, by code: who, when and where the request means.

The model read the request into spans; nothing here lets it decide what a span means when
grammar, the people file, WordNet or arithmetic can. It is asked only to pick between
options code built (which of two people a first name means, which place a phrase says, an
age read as numbers), and every decision keeps its reason for the trace.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from immich_memories.free_text.homes import Home
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPerson
from immich_memories.free_text.reading import (
    Asker,
    ask_again_if_cut,
    choose,
    object_schema,
    question,
    three_orders,
    words_of,
)

# The owner's own words for themself. The library is the owner's point of view: "I" and "me"
# usually stand behind the camera, so they anchor facts (an age, a home), never a face.
_FIRST_PERSON = frozenset(
    {"i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "ourselves"}
)
# "We" is the owner and their partner: "our wedding" is the two of them.
_WE = frozenset({"we", "us", "our", "ours", "ourselves"})
_PARTNER_ROLE = "partner"

_AGE = """The request says when its photos were taken (time_words). Does it give that time as a
person's age (is_age)? Then give the youngest and the oldest age it means and whose age it is.
Reason first. Return JSON."""
_DATES = """Give the date range the photos were taken in (YYYY-MM-DD, or null for no bound). Use the
facts given: people's birth dates, when the owner moved into each home, years written in the
request, today's date. A request that runs on ("since", "along the years") leaves the end open.
Return JSON."""
_SAID_BY_OWNER = "the owner, who says I, me, my, we, our"
# Years written in the request are pattern work: four digits from 1800 to 2099.
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_ISO_DATE = {"type": ["string", "null"], "pattern": "^[12][0-9]{3}-[01][0-9]-[0-3][0-9]$"}

# The prepositions a trailing time phrase starts with: "along the years", "over the summers".
_TIME_PREPOSITIONS = frozenset(
    {"along", "over", "through", "across", "during", "throughout", "since", "in", "for"}
)

_WHICH_PERSON = "Which of these people does the owner's request mean? Pick one. Return JSON."


@dataclass(frozen=True)
class Reason:
    """One decision: the request's words it read, the rule or question, what came out."""

    said: str
    rule: str
    outcome: str

    def line(self) -> str:
        """The decision as the trace prints it."""
        words = f'your words "{self.said}"' if self.said else "nothing said"
        return f"{words} -> {self.outcome} ({self.rule})"


@dataclass(frozen=True)
class Household:
    """What the library knows of the owner's household: the people file and the homes."""

    people: Mapping[str, LibraryPerson]
    owner_id: str | None = None
    homes: tuple[Home, ...] = ()

    @property
    def owner(self) -> LibraryPerson | None:
        """The owner's people-file entry, when the owner is identified."""
        return self.people.get(self.owner_id) if self.owner_id else None


@dataclass(frozen=True)
class WhoLink:
    """Who the request is about."""

    # People-file persons whose face must be recognised in the photo's episode.
    present: tuple[str, ...] = ()
    # Persons whose facts date or place the request: the owner for "I", the partner for
    # "we", and everyone present.
    anchors: tuple[str, ...] = ()
    # "children" or "people": a plural word for people asks for company, no one in particular.
    company: str | None = None
    reasons: tuple[Reason, ...] = ()


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def link_who(
    request: str,
    who: Sequence[str],
    household: Household,
    lexicon: Lexicon,
    asker: Asker,
) -> WhoLink:
    """The people a request names, by grammar and the people file, never by the model's guess.

    First-person words anywhere in the request ("our wedding" reads as a what) are the owner,
    and "we" adds the partner by role. In the who spans, a name or a people-file role
    requires that person's face; a plural word for people asks for company ("children" when
    WordNet says the word is young). The model only picks between people one word fits.
    """
    people = household.people
    owner = household.owner
    reasons: list[Reason] = []
    anchors: list[str] = []
    said = set(words_of(request))
    first_person = sorted(said & _FIRST_PERSON)
    if first_person and owner:
        anchors.append(owner.person_id)
        reasons.append(
            Reason(
                ", ".join(first_person),
                "first person: dates and homes only, no face needed (you usually hold the camera)",
                f"you ({owner.name})",
            )
        )
    if said & _WE:
        partners = [
            person
            for person in people.values()
            if person.role and lexicon.names_role(person.role, _PARTNER_ROLE)
        ]
        anchors += [person.person_id for person in partners]
        if partners:
            reasons.append(
                Reason(
                    ", ".join(sorted(said & _WE)),
                    "we: you and your partner, by the role in your people file",
                    ", ".join(person.name for person in partners),
                )
            )
    present: list[str] = []
    company: str | None = None
    for span in who:
        found, plural_people, span_reasons = _people_in(request, span, people, lexicon, asker)
        present += found
        company = company or plural_people
        reasons += span_reasons
    present = list(dict.fromkeys(present))
    return WhoLink(
        present=tuple(present),
        anchors=tuple(dict.fromkeys(anchors + present)),
        company=company,
        reasons=tuple(reasons),
    )


def _people_in(
    request: str,
    span: str,
    people: Mapping[str, LibraryPerson],
    lexicon: Lexicon,
    asker: Asker,
) -> tuple[list[str], str | None, list[Reason]]:
    tokens = [token.removesuffix("'s").removesuffix("’s") for token in words_of(span)]
    found: list[str] = []
    company: str | None = None
    reasons: list[Reason] = []
    for index, token in enumerate(tokens):
        if token in _FIRST_PERSON:
            continue
        named, rule = _matches(" ".join(tokens[index : index + 2]), token, people, lexicon)
        if not named:
            kind = _company_of(token, lexicon)
            if kind:
                company = company or kind
                reasons.append(
                    Reason(
                        token,
                        f"a plural word for {kind}; a caption naming {kind} shows it",
                        f"{kind} must be in the photos, no one in particular",
                    )
                )
            continue
        if len(named) > 1:
            picked, votes = _which(request, named, asker)
            rule += f"; {len(named)} fit, the model picked {picked.name} ({_tally(votes)})"
            named = [picked]
        found += [person.person_id for person in named]
        reasons.append(
            Reason(
                token,
                f"{rule}: recognised faces required, per episode",
                ", ".join(person.name for person in named),
            )
        )
    return found, company, reasons


def _matches(
    pair: str, token: str, people: Mapping[str, LibraryPerson], lexicon: Lexicon
) -> tuple[list[LibraryPerson], str]:
    named = _named(pair, token, people)
    if named:
        return named, "a name in your people file"
    # Only a singular noun names a role: a plural of people asks for company instead.
    if lexicon.noun_base(token) != token:
        return [], ""
    roles = [p for p in people.values() if p.role and lexicon.names_role(token, p.role)]
    return roles, "a role in your people file"


def _company_of(token: str, lexicon: Lexicon) -> str | None:
    # A plural of people ("friends") asks for company; "the cars" is not anyone.
    base = lexicon.noun_base(token)
    if base is None or base == token or not lexicon.is_human(token):
        return None
    return "children" if lexicon.is_young(token) else "people"


def _named(pair: str, token: str, people: Mapping[str, LibraryPerson]) -> list[LibraryPerson]:
    full = [person for person in people.values() if _fold(person.name) == _fold(pair)]
    if full:
        return full
    return [
        person
        for person in people.values()
        if person.name.split() and _fold(person.name.split()[0]) == _fold(token)
    ]


def _which(
    request: str, candidates: Sequence[LibraryPerson], asker: Asker
) -> tuple[LibraryPerson, Counter[str]]:
    labels = {
        f"{person.name} ({person.role})" if person.role else person.name: person
        for person in candidates
    }
    picked, votes = choose(asker, _WHICH_PERSON, {"owner_request": request}, list(labels))
    return labels[picked], Counter({labels[label].name: n for label, n in votes.items()})


def _tally(votes: Counter[str]) -> str:
    if not votes:
        return "no majority: the first option"
    return ", ".join(f"{option} {count}/3" for option, count in votes.most_common())


@dataclass(frozen=True)
class WhenLink:
    """The days the request's photos were taken in; None is no bound."""

    start: date | None = None
    end: date | None = None
    reasons: tuple[Reason, ...] = ()


def link_when(
    request: str,
    when: Sequence[str],
    who: WhoLink,
    household: Household,
    asker: Asker,
    *,
    today: date,
) -> WhenLink:
    """The request's dates: an age read by the model as numbers with the calendar in code, or
    the model dating the request from the facts given; nothing said, nothing asked.

    The model wrote two years for a decade when it did the calendar itself, so it only reads
    the age ("in our 20s": 20 to 29, the owner's) and code adds it to the birth date. The
    dates question runs only when the request has time words, written years or people
    present; a request that says none of these is any time.
    """
    said = " | ".join(when)
    anchors = [household.people[p] for p in who.anchors if p in household.people]
    age = _age(request, when, anchors, household.owner_id, asker)
    if age is not None:
        name, born, youngest, oldest, votes = age
        first = _birthday(born, youngest)
        last = _birthday(born, oldest + 1) - timedelta(days=1)
        rule = (
            f"the model read an age: {youngest} to {oldest}, {name}'s ({votes}); "
            f"code: born {born.isoformat()}"
        )
        return WhenLink(first, last, (Reason(said, rule, f"{first} to {last}"),))
    years = sorted(set(_YEAR.findall(request)))
    if not (when or years or who.present):
        return WhenLink(reasons=(Reason("", "no time words, years or people to date", "any time"),))
    start, end = _dates(request, when, years, anchors, household, asker, today)
    rule = "the model dated it from the facts given (births, moving-in dates, years you wrote)"
    outcome = f"{start or 'any time'} to {end or 'open'}"
    return WhenLink(start, end, (Reason(said, rule, outcome),))


def _age(
    request: str,
    when: Sequence[str],
    anchors: Sequence[LibraryPerson],
    owner_id: str | None,
    asker: Asker,
) -> tuple[str, date, int, int, str] | None:
    dated = {person.name: person for person in anchors if person.birth_date}
    born = {name: person.birth_date for name, person in dated.items() if person.birth_date}
    if not when or not dated:
        return None
    orders = list(dict.fromkeys(tuple(order) for order in three_orders(list(dated))))
    votes: Counter[tuple[str, int, int]] = Counter()
    for order in orders:
        people = [
            {
                "name": name,
                "born": str(dated[name].birth_date),
                "who": _SAID_BY_OWNER if dated[name].person_id == owner_id else "",
            }
            for name in order
        ]
        got = ask_again_if_cut(
            asker,
            question(_AGE, {"owner_request": request, "time_words": list(when), "people": people}),
            object_schema(
                reason={"type": "string", "maxLength": 200},
                is_age={"type": "boolean"},
                whose_age={"type": "string", "enum": list(order)},
                age_from={"type": "integer", "minimum": 0, "maximum": 120},
                age_to={"type": "integer", "minimum": 0, "maximum": 120},
            ),
            max_tokens=300,
        )
        # A yes/no gate, then plain numbers: offered a null, the model answered null after
        # reasoning "yes".
        if got is None or got.get("is_age") is not True or got.get("whose_age") not in dated:
            continue
        youngest = got.get("age_from")
        if not isinstance(youngest, int):
            continue
        oldest = got.get("age_to")
        oldest = max(oldest, youngest) if isinstance(oldest, int) else youngest
        votes[(got["whose_age"], youngest, oldest)] += 1
    best = votes.most_common(1)
    # A majority of the distinct asks: one person means one ask, and its answer stands.
    if not best or best[0][1] < min(2, len(orders)):
        return None
    (name, youngest, oldest), count = best[0]
    return name, born[name], youngest, oldest, f"{count}/{len(orders)}"


def _birthday(born: date, age: int) -> date:
    try:
        return born.replace(year=born.year + age)
    except ValueError:
        # Born on 29 February: the birthday in a common year is 28 February.
        return born.replace(year=born.year + age, day=28)


def _dates(
    request: str,
    when: Sequence[str],
    years: Sequence[str],
    anchors: Sequence[LibraryPerson],
    household: Household,
    asker: Asker,
    today: date,
) -> tuple[date | None, date | None]:
    facts = {
        "owner_request": request,
        "what_the_request_says_about_time": list(when),
        "today": today.isoformat(),
        "years_in_request": list(years),
        "people": [
            {"name": person.name, "born": str(person.birth_date or "unknown")} for person in anchors
        ],
        "homes": [
            {
                "moved_in": str(home.since or "before the library"),
                "moved_out": str(home.until or ""),
            }
            for home in household.homes
        ],
    }
    got = ask_again_if_cut(
        asker,
        question(_DATES, facts),
        object_schema(date_from=_ISO_DATE, date_to=_ISO_DATE),
        max_tokens=300,
    )
    if got is None:
        return None, None
    return _day(got.get("date_from")), _day(got.get("date_to"))


def _day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def time_cut(phrase: str, lexicon: Lexicon) -> str:
    """The phrase without a trailing time phrase: from the last preposition whose words end on
    a period of time (WordNet's time_period, not a list). "closed eyes along the years" is
    "closed eyes"; the years are when, not what the photos show.
    """
    tokens = phrase.split()
    if len(tokens) < 2 or not lexicon.is_time_period(tokens[-1]):
        return phrase
    for index in range(len(tokens) - 2, -1, -1):
        if tokens[index].lower() in _TIME_PREPOSITIONS:
            return " ".join(tokens[:index])
    return phrase
