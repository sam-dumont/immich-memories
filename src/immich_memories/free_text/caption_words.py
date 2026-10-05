"""What a caption names as a person, in English, and which specific company kind (#2061).

Captions are always written in English (the captioner never writes another language), so
these tables need no locale: a caption word is matched once, against a curated list, not
"any WordNet person sense" (real WordNet's first-sense hypernym chain still reaches a
person synset for ordinary nouns, such as "fields" or "village", that are not about people).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------
# Caption-side (English only): what counts as a person, and which specific kind.
# ---------------------------------------------------------------------------------------

# Curated, not "any WordNet person sense": real WordNet's first-sense hypernym chain
# still reaches a person synset for common nouns that are not about people at all. Only a
# word on this list names a person on a caption (#2061).
PERSON_WORDS = frozenset(
    {
        "person",
        "people",
        "human",
        "humans",
        "man",
        "men",
        "woman",
        "women",
        "child",
        "children",
        "kid",
        "kids",
        "boy",
        "boys",
        "girl",
        "girls",
        "baby",
        "babies",
        "toddler",
        "toddlers",
        "infant",
        "infants",
        "teenager",
        "teenagers",
        "teen",
        "teens",
        "adolescent",
        "adolescents",
        "adult",
        "adults",
        "family",
        "families",
        "couple",
        "couples",
        "friend",
        "friends",
        "parent",
        "parents",
        "folks",
        "crowd",
        "crowds",
        "audience",
        "audiences",
        "spectator",
        "spectators",
        "onlooker",
        "onlookers",
        "bystander",
        "bystanders",
        "visitor",
        "visitors",
        "tourist",
        "tourists",
        "guest",
        "guests",
        "hiker",
        "hikers",
        "skier",
        "skiers",
        "player",
        "players",
        "lady",
        "ladies",
        "pedestrian",
        "pedestrians",
        "cyclist",
        "cyclists",
        "rider",
        "riders",
        "performer",
        "performers",
        "musician",
        "musicians",
        "singer",
        "singers",
        "dancer",
        "dancers",
        "actor",
        "actors",
        "entertainer",
        "entertainers",
        "band",
        "bands",
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
        "djs",
        # Family relations WordNet's person hypernym reached that the curated list missed
        # (#2061 round 3): a captioner writes "son" or "mother", not "child" or "adult".
        "son",
        "sons",
        "daughter",
        "daughters",
        "father",
        "fathers",
        "mother",
        "mothers",
        "newborn",
        "newborns",
        "grandchild",
        "grandchildren",
        "grandson",
        "grandsons",
        "granddaughter",
        "granddaughters",
        "grandpa",
        "grandma",
        "grandfather",
        "grandmother",
        "stranger",
        "strangers",
        "face",
        "faces",
        # Performer evidence that is not a role noun: what the caption shows them doing,
        # or the props around them (Case 30: audience-framed shots with no performer noun).
        "singing",
        "performing",
        "microphone",
        "microphones",
    }
)

# A specific company kind within PERSON_WORDS: "children", "teens", "performers" or
# "audience". A word not here but still in PERSON_WORDS is generic "people".
CAPTION_KIND: dict[str, str] = {
    **dict.fromkeys(
        (
            "child",
            "children",
            "kid",
            "kids",
            "toddler",
            "toddlers",
            "infant",
            "infants",
            "baby",
            "babies",
            "newborn",
            "newborns",
            "grandchild",
            "grandchildren",
        ),
        "children",
    ),
    **dict.fromkeys(
        ("teenager", "teenagers", "teen", "teens", "adolescent", "adolescents"), "teens"
    ),
    **dict.fromkeys(
        (
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
            "djs",
            "singing",
            "performing",
            "microphone",
            "microphones",
        ),
        "performers",
    ),
    **dict.fromkeys(
        (
            "crowd",
            "crowds",
            "audience",
            "audiences",
            "spectator",
            "spectators",
            "onlooker",
            "onlookers",
            "bystander",
            "bystanders",
        ),
        "audience",
    ),
}


def caption_kind_of(word: str) -> str | None:
    """The specific company kind a caption word names ("children", "teens", "performers",
    "audience"), or "people" for any other word in `PERSON_WORDS`, or None for neither."""
    folded = word.lower()
    if folded in CAPTION_KIND:
        return CAPTION_KIND[folded]
    return "people" if folded in PERSON_WORDS else None


# Every company kind this package names, for a caller that needs to tell a kind word
# ("people", "performers") apart from an ordinary excluded phrase ("toy cars") (#2061).
KINDS = frozenset({"people", "children", "teens", "performers", "audience"})
