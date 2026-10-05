"""Negation, "only" and company words for every supported locale (#2061).

WordNet is English-only and unreliable even there for this purpose: `noun_base("humans")`
is "humans" (an irregular plural WordNet's morphy does not reduce), and plenty of ordinary
nouns ("fields", "village", "modern") sit under a person synset somewhere in their hypernym
tree, which made an "absent people" request drop empty landscapes. Everything here is a
curated word list instead: explicit, small, and checked against the real corpus by its own
tests rather than trusted to WordNet's morphology or hypernym depth.

The request's own words are read in whichever of the 14 supported locales
(`immich_memories.i18n.SUPPORTED_LOCALES`) the owner typed; the caption, always English (the
captioner never writes another language), is read by `caption_words.py` instead.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _folded(words: Iterable[str]) -> frozenset[str]:
    """A request-side word table, each entry folded the same way a request's own word is
    before it is looked up -- so a word written with its real accent in this module's
    source (readable) still matches (#2061). Hand-pre-folding every entry is how
    "людей" (its trailing letter decomposes under NFKD) silently stopped matching."""
    return frozenset(_fold(word) for word in words)


# ---------------------------------------------------------------------------------------
# Request-side (every supported locale): negation, "only", conjunctions, company words.
# ---------------------------------------------------------------------------------------

# Pure function words: never a company word themselves, skipped when scanning a clause for
# who it names. One locale per line in `i18n.SUPPORTED_LOCALES`'s order.
_NEGATION: frozenset[str] = _folded(
    {
        "no",
        "not",
        "without",
        "none",
        "except",
        "excluding",  # en
        "sans",
        "pas",
        "aucun",
        "aucune",
        "sauf",
        "excepte",
        "hormis",  # fr
        "zonder",
        "geen",  # nl
        "ohne",
        "kein",
        "keine",
        "keinen",
        "ausser",  # de
        "sin",
        "ningun",
        "ninguna",
        "ninguno",
        "excepto",  # es
        "senza",
        "nessun",
        "nessuna",
        "nessuno",
        "tranne",  # it
        "sem",
        "nenhum",
        "nenhuma",  # pt-BR, pt-PT
        "bez",
        "zadnych",
        "zadnego",
        "nie",
        "oprocz",  # pl
        "utan",
        "ingen",
        "inga",
        "behalve",  # sv (and nl)
        "без",
        "нет",
        "никаких",
        "кроме",  # ru
    }
)
# Dual-role words: an absolute negative pronoun that is both a negation marker AND the
# company word itself ("il n'y a personne": nobody; "nessuno" alone: nobody), so each is
# always read as `people`, never cancelled by another negation marker in the same clause
# ("sans personne" is one negation, not two that cancel back to required). Counted toward a
# clause's own negation unconditionally, but never skipped, so they still reach the lookup.
_NEGATION_ALSO_COMPANY: frozenset[str] = _folded(
    {
        "personne",  # fr (also "il n'y a personne")
        "nobody",
        "noone",  # en
        "niemand",  # de, nl
        "nadie",  # es
        "nessuno",  # it
        "ninguem",  # pt-BR, pt-PT
        "nikt",  # pl
        "ingen",  # sv (also a pure marker: "inga" is the plural form used before a noun)
        "никто",  # ru
    }
)

_EXCLUSIVE: frozenset[str] = _folded(
    {
        "only",  # en
        "seulement",
        "uniquement",
        "que",  # fr
        "alleen",
        "enkel",  # nl
        "nur",  # de
        "solo",
        "solamente",  # es (and it)
        "soltanto",  # it
        "apenas",
        "so",
        "somente",  # pt-BR, pt-PT
        "tylko",  # pl
        "bara",
        "endast",  # sv
        "только",  # ru
    }
)

# Clause connectors: "and", "but", "with" in every locale, used only to split a who-span
# into its own negated or positive clauses ("avec les enfants, pas de pluie").
_CONJUNCTIONS: frozenset[str] = _folded(
    {
        "and",
        "but",
        "with",  # en
        "et",
        "mais",
        "avec",  # fr
        "en",
        "maar",
        "met",  # nl
        "und",
        "aber",
        "mit",  # de
        "y",
        "e",
        "pero",
        "con",  # es, it
        "ma",  # it
        "mas",
        "com",  # pt-BR, pt-PT
        "i",
        "ale",
        "z",  # pl
        "och",
        "men",
        "med",  # sv
        "и",
        "но",
        "с",  # ru
    }
)

# The bare, generic word for "people" ("people", "humans", "human", "persons", "folks"):
# never a positive, required company on its own. "first picture of recurring people" is a
# computed selection (`facts.people`), not a generic company ask, and a plain WordNet plural
# check used to read "people" as its own singular (no distinct plural form) and so never set
# it either; this table keeps that same no-op for the positive case on purpose, while still
# reading it when negated ("no people", "sans personnes") -- #2061's actual bug.
_BARE_PEOPLE_WORDS: frozenset[str] = _folded(
    {
        "people",
        "humans",
        "human",
        "persons",
        "folks",
        "crowd",  # en
        "gens",
        "personnes",
        "personne",
        "humains",
        "humain",  # fr
        "mensen",
        "personen",  # nl
        "menschen",
        "leute",  # de
        "personas",
        "gente",
        "humanos",  # es
        "persone",
        "umani",  # it
        "pessoas",  # pt-BR, pt-PT
        "ludzie",
        "ludzi",
        "osoby",  # pl (nominative and the genitive "bez ludzi" takes)
        "manniskor",
        "personer",  # sv
        "люди",
        "людей",  # ru (nominative and the genitive "без людей" takes)
        "stranger",
        "strangers",
        "tourist",
        "tourists",
        "face",
        "faces",  # en: a face stands for the person it belongs to
        "etranger",
        "etrangers",  # fr
        "vreemdeling",
        "vreemdelingen",  # nl
        "fremder",
        "fremde",  # de
        "extrano",
        "extranos",  # es
        "estraneo",
        "estranei",  # it
        "estranho",
        "estranhos",  # pt-BR, pt-PT
        "nieznajomy",
        "nieznajomi",  # pl
        "framling",
        "framlingar",  # sv
        "незнакомец",
        "незнакомцы",  # ru
        # Absolute negative pronouns (#2061): each one already means "nobody" on its own,
        # so it is a bare people-word even outside `_NEGATION_ALSO_COMPANY`'s own clause.
        "nobody",
        "noone",
        "niemand",
        "nadie",
        "nessuno",
        "ninguem",
        "nikt",
        "никто",
    }
)
# A relational plural still asks for company positively ("with friends"): it names a group
# the request itself picked out, unlike the bare noun above.
_RELATIONAL_WORDS: frozenset[str] = _folded(
    {
        "friends",
        "friend",
        "family",
        "guests",
        "visitors",  # en
        "amis",
        "ami",
        "famille",  # fr
        "vrienden",
        "familie",  # nl, de (same spelling)
        "freunde",  # de
        "amigos",
        "familia",  # es, pt-BR, pt-PT
        "amici",
        "famiglia",  # it
        "przyjaciele",
        "rodzina",  # pl
        "vanner",
        "familj",  # sv
        "друзья",
        "семья",  # ru
        # Grandparents: a specific relation, counted the same way "friends"/"family" are.
        "grandpa",
        "grandma",
        "grandfather",
        "grandmother",  # en
        "grand-pere",
        "grand-mere",  # fr
        "opa",
        "oma",  # nl, de
        "abuelo",
        "abuela",  # es
        "nonno",
        "nonna",  # it
        "avo",
        "avos",  # pt-BR, pt-PT
        "dziadek",
        "babcia",  # pl
        "morfar",
        "farfar",
        "mormor",
        "farmor",  # sv
        "дедушка",
        "бабушка",  # ru
        # An absolute positive pronoun ("everyone"): the opposite of "nobody", always a
        # people word on its own, never gated to a negated clause the way "people" is.
        "everyone",
        "everybody",  # en
        "tous",
        "toutes",  # fr
        "iedereen",  # nl
        "alle",  # de, sv
        "todos",
        "todas",  # es, pt-BR, pt-PT
        "tutti",
        "tutte",  # it
        "wszyscy",  # pl
        "все",  # ru
    }
)
_PEOPLE_WORDS: frozenset[str] = _BARE_PEOPLE_WORDS | _RELATIONAL_WORDS
_CHILDREN_WORDS: frozenset[str] = _folded(
    {
        "children",
        "kids",
        "child",
        "kid",  # en
        "enfants",
        "enfant",  # fr
        "kinderen",
        "kind",  # nl
        "kinder",  # de
        "ninos",
        "nino",
        "ninas",
        "nina",  # es
        "bambini",
        "bambino",
        "bambina",
        "bambine",  # it
        "criancas",
        "crianca",  # pt-BR, pt-PT
        "dzieci",  # pl
        "barn",  # sv
        "дети",  # ru
    }
)
_TEEN_WORDS: frozenset[str] = _folded(
    {
        "teens",
        "teenagers",
        "teen",
        "teenager",  # en, de ("Teenager" same spelling)
        "ados",
        "adolescents",
        "adolescent",
        "adolescente",
        "adolescentes",  # fr, es, pt-BR, pt-PT
        "tieners",
        "tiener",  # nl
        "jugendliche",  # de
        "adolescenti",  # it
        "nastolatkowie",
        "nastolatek",  # pl
        "tonaringar",
        "tonaring",  # sv
        "подростки",  # ru
    }
)
_PERFORMER_WORDS: frozenset[str] = _folded(
    {
        "performer",
        "performers",
        "musician",
        "musicians",
        "singer",
        "singers",
        "band",
        "bands",
        "dancer",
        "dancers",
        "actor",
        "actors",
        "entertainer",
        "entertainers",
        "drummer",
        "drummers",
        "guitarist",
        "guitarists",
        "pianist",
        "pianists",
        "violinist",
        "violinists",
        "rapper",
        "rappers",
        "choir",
        "choirs",
        "orchestra",
        "orchestras",
        "dj",
        "djs",  # en
        "musicien",
        "musiciens",
        "musicienne",
        "musiciennes",
        "chanteur",
        "chanteurs",
        "chanteuse",
        "chanteuses",
        "danseur",
        "danseurs",
        "danseuse",
        "danseuses",
        "artiste",
        "artistes",
        "batteur",
        "batteurs",
        "guitariste",
        "guitaristes",
        "pianiste",
        "pianistes",
        "violoniste",
        "violonistes",
        "rappeur",
        "rappeurs",
        "choeur",
        "choeurs",
        "orchestre",
        "orchestres",  # fr
        "muzikant",
        "muzikanten",
        "zanger",
        "zangers",
        "danser",
        "dansers",  # nl
        "musiker",
        "musikerin",
        "sanger",
        "sangerin",
        "tanzer",
        "tanzerin",
        "schlagzeuger",
        "gitarrist",
        "geiger",
        "chor",
        "orchester",  # de
        "musico",
        "musicos",
        "cantante",
        "cantantes",
        "bailarin",
        "bailarines",
        "bailarina",
        "bailarinas",
        "baterista",
        "guitarrista",
        "pianista",
        "violinista",
        "coro",
        "orquesta",  # es
        "musicista",
        "musicisti",
        "cantanti",
        "ballerino",
        "ballerini",
        "ballerina",
        "ballerine",
        "batterista",
        "chitarrista",  # it (orchestra: same as en)
        "cantores",
        "dancarinos",
        "dancarina",  # pt-BR, pt-PT
        "muzycy",
        "muzyk",
        "spiewacy",
        "spiewak",
        "tancerze",
        "tancerz",  # pl
        "sangare",
        "dansare",  # sv
        "музыканты",
        "певцы",
        "танцоры",  # ru
    }
)
_AUDIENCE_WORDS: frozenset[str] = _folded(
    {
        "crowd",
        "crowds",
        "audience",
        "audiences",
        "spectator",
        "spectators",  # en
        "foule",
        "public",  # fr
        "menigte",
        "publiek",  # nl
        "menge",
        "publikum",
        "zuschauer",  # de
        "multitud",
        "publico",  # es, pt-BR, pt-PT
        "folla",
        "pubblico",  # it
        "multidao",  # pt-BR, pt-PT
        "tlum",
        "publiczność",
        "publicznosc",  # pl
        "publik",
        "folkmassa",  # sv
        "толпа",
        "зрители",  # ru
    }
)

# CJK (no whitespace, no plural morphology): substring markers over the clause text
# itself rather than tokens. Each locale's negation, "only" and company substrings.
_CJK_LOCALES = frozenset({"ja", "ko", "zh-Hans"})
CJK_NEGATION: dict[str, tuple[str, ...]] = {
    "ja": ("なし", "ない", "抜き", "除いて"),
    "ko": ("없이", "없는", "빼고", "제외"),
    "zh-Hans": ("没有", "不要", "无", "不含", "除了", "以外"),
}
CJK_EXCLUSIVE: dict[str, tuple[str, ...]] = {
    "ja": ("だけ", "のみ"),
    "ko": ("만", "뿐"),
    "zh-Hans": ("只", "仅"),
}
CJK_PEOPLE: dict[str, tuple[str, ...]] = {
    "ja": ("人間", "人々", "人"),
    "ko": ("사람들", "사람", "인간"),
    "zh-Hans": ("人们", "人"),
}
CJK_CHILDREN: dict[str, tuple[str, ...]] = {
    "ja": ("子供",),
    "ko": ("아이들",),
    "zh-Hans": ("孩子", "儿童"),
}
CJK_PERFORMERS: dict[str, tuple[str, ...]] = {
    "ja": ("ミュージシャン", "演奏者", "バンド"),
    "ko": ("음악가", "연주자", "밴드"),
    "zh-Hans": ("音乐家", "演奏者", "乐队"),
}

_KIND_TABLES: tuple[tuple[frozenset[str], str], ...] = (
    (_CHILDREN_WORDS, "children"),
    (_TEEN_WORDS, "teens"),
    (_PERFORMER_WORDS, "performers"),
    (_AUDIENCE_WORDS, "audience"),
    (_PEOPLE_WORDS, "people"),
)


def request_kind_of(word: str, *, negated: bool = False) -> str | None:
    """The company kind the request's own word names, in any supported locale, or None.

    A bare, generic "people" word (not a specific kind, not a relational word like
    "friends") is read only when `negated`: see `_BARE_PEOPLE_WORDS`.
    """
    folded = _fold(word)
    if not negated and folded in _BARE_PEOPLE_WORDS:
        return None
    for words, kind in _KIND_TABLES:
        if folded in words:
            return kind
    return None


def cjk_locale_of(text: str) -> str | None:
    """Which CJK locale's script the text is written in, or None for a spaced script.

    Kanji (`\\u4e00`-`\\u9fff`) are shared with Chinese, so hiragana/katakana (ja-only) and
    hangul (ko-only) are checked over the WHOLE text first; a kanji-only text that reaches
    neither falls to zh-Hans. Scanning char by char and returning on the first script seen
    would misread "風景なし" (kanji before its own hiragana) as Chinese (#2061).
    """
    if any("぀" <= char <= "ヿ" for char in text):
        return "ja"
    if any("가" <= char <= "힣" for char in text):
        return "ko"
    if any("一" <= char <= "鿿" for char in text):
        return "zh-Hans"
    return None


_CJK_KIND_TABLES: tuple[tuple[dict[str, tuple[str, ...]], str], ...] = (
    (CJK_CHILDREN, "children"),
    (CJK_PERFORMERS, "performers"),
    (CJK_PEOPLE, "people"),
)


def cjk_company(text: str) -> tuple[bool, bool, str | None]:
    """(negated, exclusive, kind) read by substring over a whole CJK span.

    ja/ko/zh-Hans have no whitespace and no plural morphology, so the word-boundary regex
    every other locale's clause splitting relies on finds nothing to split on; the whole
    span is read as one clause by substring instead (#2061).
    """
    locale = cjk_locale_of(text)
    if locale is None:
        return False, False, None
    negated = any(marker in text for marker in CJK_NEGATION.get(locale, ()))
    exclusive = any(marker in text for marker in CJK_EXCLUSIVE.get(locale, ()))
    kind = next(
        (name for table, name in _CJK_KIND_TABLES if any(m in text for m in table.get(locale, ()))),
        None,
    )
    return negated, exclusive, kind


@dataclass(frozen=True)
class Clause:
    """One piece of a request: its own words, and whether it is negated or exclusive.

    A double negation ("not without the kids") cancels out: `negated` is true only when an
    odd number of pure markers were said, the way "not" and "without" each stand for a whole
    negation on their own. An absolute negative pronoun ("nobody", "nessuno", "personne" in
    "ne...personne") is never part of that count: it always means absence on its own, so
    "sans personne" is one negation, not two that cancel back to required.
    """

    words: tuple[str, ...]
    negated: bool
    exclusive: bool

    def negated_at(self, index: int) -> bool:
        """Whether the word at `index` is inside a negation's scope: a marker before it in
        this same clause, never one that only comes after ("kids not wearing hats" keeps the
        kids -- the negation is for "wearing hats", said after "kids", not for "kids")."""
        pure = sum(_fold(t) in _NEGATION for t in self.words[:index])
        dual = any(_fold(t) in _NEGATION_ALSO_COMPANY for t in self.words[:index])
        return bool(pure % 2) or dual


# Elided articles before a vowel ("d'enfants", "l'ami", "qu'il", "n'y") glue onto the next
# word under the plain word-boundary regex every other reader uses; split them first so the
# noun after them is its own token.
_ELISION = re.compile(r"\b([dlqnjmts])['’](\w)", re.IGNORECASE)


def elide(text: str) -> str:
    """The text with a leading elision ("d'", "l'", "qu'", "n'"...) split from its word."""
    return _ELISION.sub(r"\1' \2", text)


def clauses(text: str) -> list[Clause]:
    """The who-span split into its own negated-or-not clauses, by comma/semicolon and by a
    connector word ("and", "but", "with", and each supported locale's own)."""
    pieces = re.split(r"[,;]", elide(text))
    return [clause for piece in pieces for clause in _split_on_conjunctions(_tokens(piece))]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w'’]+", text.lower())


def _split_on_conjunctions(tokens: Sequence[str]) -> list[Clause]:
    groups: list[list[str]] = [[]]
    for token in tokens:
        if _fold(token) in _CONJUNCTIONS and groups[-1]:
            groups.append([])
            continue
        groups[-1].append(token)
    return [_clause(group) for group in groups if group]


def _clause(tokens: Sequence[str]) -> Clause:
    pure = sum(_fold(t) in _NEGATION for t in tokens)
    dual = any(_fold(t) in _NEGATION_ALSO_COMPANY for t in tokens)
    exclusive = any(_fold(t) in _EXCLUSIVE for t in tokens)
    return Clause(tuple(tokens), bool(pure % 2) or dual, exclusive)


def is_self_negating(token: str) -> bool:
    """Whether the token is an absolute negative pronoun ("nobody", "personne"): it means
    absence on its own, whatever came before it in the clause (#2061)."""
    return _fold(token) in _NEGATION_ALSO_COMPANY


def is_skip_word(token: str) -> bool:
    """Whether the token is a pure function word, never itself a company or a name.

    An absolute negative pronoun ("nobody", "nessuno") is never skipped even though some of
    them double as a plain negation marker too ("nessun bambino"): it is also the company
    word itself and must still reach the lookup (#2061).
    """
    folded = _fold(token)
    if folded in _NEGATION_ALSO_COMPANY:
        return False
    return folded in _NEGATION or folded in _EXCLUSIVE
