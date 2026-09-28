"""The translation: an owner's sentence becomes an explicit filter spec, printed before it runs.

One small Gemma question per field, each answered from choices code builds out of the owner's
own data (the people file, the homes list with the names Immich gives those areas, the words of
the request). Gemma translates; code only offers the choices and applies the answers.

    people        who must be there (people file), and whether their faces must be recognised
    when          the date range, from the request's words and stored dates (births, moves)
    where         anywhere / home at the time / one particular home / away on trips
    text_in_photo words written in the photos (a club on a jersey), read by Immich OCR
    meaning       what the photos show, in visible terms: what belongs and what looks close but not
    question      the yes/no question one photo must pass
    caption_words the words captions use for it (finds candidates; never decides)
    shape         one moment / along the years / how it changed / first times / a collection
"""

import json
import math
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

import yaml
from pathlib import Path

from discovery import GLUE
from experiment_data import ROOT

# The owner's house, measured: 19,298 pictures since 2016 lie within 50 m of it, 19,491 within
# 200 m, then the street starts (20,848 at 1 km, 29,450 at the trip detector's 10 km).
AT_HOME_KM = 0.15
ARTICLES = {"a", "an", "the", "some", "two", "three", "several", "his", "her", "their", "its"}
SHAPES = ["one moment or event", "along the years", "how something changed over time",
          "first times", "a collection of one kind of thing"]


def _schema(**props):
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def homes(library, assets):
    """The homes list with each one's end date and the area name Immich gives its pictures."""
    path = ROOT / "homes.yaml"
    listed = sorted((yaml.safe_load(path.read_text()) or {}).get("homes") or [], key=lambda h: str(h["since"])) \
        if path.exists() else []
    out = []
    for n, h in enumerate(listed):
        until = str(listed[n + 1]["since"]) if n + 1 < len(listed) else None
        where = (h["lat"], h["lon"])
        areas = Counter(r.get("city") for r in library.rows
                        if (a := assets.get(r["asset_id"])) and km(where, (a.exif_info.latitude, a.exif_info.longitude)) <= AT_HOME_KM)
        out.append({"name": h.get("name") or f"home {n + 1}", "lat": h["lat"], "lon": h["lon"],
                    "since": str(h["since"]), "until": until,
                    "area": [c for c, _ in areas.most_common(2) if c]})
    return out


def where_options(lived):
    # Each option says what it means, as a semantic layer describes its fields: Gemma picks by meaning.
    options = {"anywhere: the request does not tie the photos to a place": ("any", None),
               "at home, wherever the owner lived when the photo was taken: what belongs to the owner's "
               "household and moves with them (their pets, life at home)": ("home_at_time", None)}
    for h in lived:
        area = f", the area Immich calls {' / '.join(h['area'])}" if h["area"] else ""
        options[f"at the {h['name']} home only ({h['since'][:4]} to {h['until'][:4] if h['until'] else 'now'}{area}): "
                "that house or flat itself, or what happened in it"] = ("home", h["name"])
    options["away from home: only when the request says holidays, trips or travel"] = ("trips", None)
    return options


def at_home_rows(library, assets, lived, which=None):
    """Rows taken at a home: `which` names one; None means the home valid on the photo's date."""
    out = set()
    for i, r in enumerate(library.rows):
        a = assets.get(r["asset_id"])
        if not a:
            continue
        day = r["taken_at"][:10]
        if which:
            candidates = [h for h in lived if h["name"] == which]
        else:
            candidates = [h for h in lived if h["since"] <= day and (h["until"] is None or day < h["until"])][-1:]
        if any(km((h["lat"], h["lon"]), (a.exif_info.latitude, a.exif_info.longitude)) <= AT_HOME_KM for h in candidates):
            out.add(i)
    return out


WHERE = '''Where were the photos this request asks for taken? Pick one of the options. Pick a place
only when the request says or clearly means it ("our house", "at home", "holidays"); otherwise
"anywhere". Reason first. Return JSON.'''

TEXT = '''Which words of the request would be written on something in the photos (a club or team name
on a jersey, a brand, a sign)? Only a name the request uses that is likely printed on things;
usually none. Return JSON.'''

SHOWS = '''List what a photo visibly shows when it belongs in this film: the subject itself, its
kinds and its visible parts, and an action when one photo can show it. Short concrete nouns or
phrases, the way a photo caption names things. No dates, places, names, feelings, ownership or
quality words. Return JSON.'''

PICK_SHOWS = '''Which of these would a photo that belongs in this film show as its subject? Pick every
one that fits: the subject, its kinds, its parts, what happens to it. Not the setting and not
things that are only nearby. Return JSON.'''

PICK_NOT = '''These phrases come from captions of the owner's photos. Which name something that does NOT
belong in this film, although it looks close? Pick only those that clearly do not belong; none
when all could belong. Return JSON.'''

SPAN = '''This film is about one moment or event that starts on date_from. How long after it do its
photos run? Pick one. Return JSON.'''
SPANS = {"one day": 0, "one week": 6, "one month": 30, "three months": 91}

SHAPE = '''What shape of film does the request ask for? Pick one. Return JSON.'''

FILTERS = '''Give the date range the photos were taken in (YYYY-MM-DD, or null for no bound), and
whether the listed people's faces must be recognised in each photo. Use the facts given (people's
birth dates, when the owner moved into each home, years written in the request, today's date, and
the film's shape). A film of one moment or event gets only the few days or weeks that moment
covers; a request that runs on ("since", "along the years") leaves the end open. Return JSON.'''


def _ask(reader, stage, key, prompt, data, schema, tokens=300):
    return reader.ask(stage, key, prompt, data, lambda a: None, tokens, schema=schema) or {}


def build_spec(reader, key, brief, library, people_named, lived, years):
    """people_named: the people the request is about (already linked); returns the spec dict."""
    options = where_options(lived)
    where = _ask(reader, "spec_where", key, WHERE, {"owner_request": brief, "options": list(options)},
                 _schema(reason={"type": "string", "maxLength": 200},
                         where={"type": "string", "enum": list(options)}))
    where_text = where.get("where") or "anywhere"
    request_words = sorted({w for w in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", brief)})
    text = _ask(reader, "spec_text", key, TEXT, {"owner_request": brief},
                _schema(words={"type": "array", "items": {"type": "string", "enum": request_words or [""]}, "maxItems": 3}))
    shows = [x.strip() for x in _ask(reader, "spec_shows", key, SHOWS, {"owner_request": brief},
             _schema(shows={"type": "array", "items": {"type": "string", "maxLength": 50}, "maxItems": 10})
             ).get("shows") or [] if x.strip()]
    shape = _ask(reader, "spec_shape", key, SHAPE, {"owner_request": brief, "options": SHAPES},
                 _schema(shape={"type": "string", "enum": SHAPES})).get("shape") or "along the years"
    date = {"type": ["string", "null"], "pattern": "^[12][0-9]{3}-[01][0-9]-[0-3][0-9]$"}
    when = _ask(reader, "spec_when", key, FILTERS, {
        "owner_request": brief, "film_shape": shape, "today": datetime.now(UTC).date().isoformat(),
        "years_in_request": years,
        "people": [{"name": p["name"], "born": str(p.get("birth_date") or "unknown")} for p in people_named],
        "homes": [{"home": h["name"], "moved_in": h["since"], "moved_out": h["until"]} for h in lived]},
        _schema(date_from=date, date_to=date, faces_required={"type": "boolean"}))
    span = None
    if shape == "one moment or event" and when.get("date_from"):
        # A moment's end is a choice among spans, not a written date (E4B wrote a one-day birth).
        span = _ask(reader, "spec_span", key, SPAN, {"owner_request": brief, "date_from": when["date_from"],
                    "options": list(SPANS)}, _schema(span={"type": "string", "enum": list(SPANS)})).get("span")
        if span:
            start = datetime.fromisoformat(when["date_from"])
            when["date_to"] = (start + timedelta(days=SPANS[span])).date().isoformat()
    kind, home = options[where_text]
    return {"english": brief, "people": [p["name"] for p in people_named],
            "people_must_appear": bool(when.get("faces_required")) and bool(people_named),
            "when": {"from": when.get("date_from"), "to": when.get("date_to")},
            "where": {"said": where_text, "kind": kind, "home": home, "why": (where.get("reason") or "")[:200]},
            "text_in_photo": [w for w in text.get("words") or [] if w],
            "seeds": shows, "span": span,
            "shape": shape}


def _used(library, word, at_least=10):
    return "_" not in word and len(library.posts.get(word, ())) >= at_least


def lexicon(library, seeds, most=25):
    """Kinds and parts of the request's nouns, in their main sense, with the parts they inherit from
    what they are (a house's rooms and floors are a building's). A word is kept only when the owner's
    captions use it and its own everyday meaning is that kind or part: WordNet lists "bus" (an old
    car) as a kind of car, and a caption's "bus" is not one. Returns {word: "kind of X" | "part of X"}."""
    from nltk.corpus import wordnet as wn

    found = {}
    for seed in seeds:
        head = wn.morphy(seed.split()[-1].lower(), wn.NOUN) or seed.split()[-1].lower()
        for synset in wn.synsets(head, pos=wn.NOUN)[:1]:
            above = [h for path in synset.hypernym_paths() for h in path[-4:]]
            parts = [m for x in [synset, *above] for m in x.part_meronyms()]
            related = [(k, "kind") for k in synset.closure(lambda x: x.hyponyms(), depth=2)]
            related += [(m, "part") for m in parts] + [(k, "part") for m in parts for k in m.hyponyms()]
            for other, how in related:
                for lemma in other.lemmas():
                    word = lemma.name().lower()
                    senses = wn.synsets(word, pos=wn.NOUN)
                    if word != head and _used(library, word) and senses and senses[0] == other:
                        found.setdefault(word, f"{how} of {head}")
    keep = sorted(found, key=lambda w: (-len(library.posts[w]), w))[:most]
    return {w: found[w] for w in keep}


def lifted(library, rows, within=None, most=15):
    """Words over-represented in `rows` against `within` (the whole library by default), by real
    frequency, not rarity: a word five captions use is noise, not a signal."""
    base = within if within is not None else range(len(library.rows))
    base = list(base)
    if not rows or len(rows) >= len(base) * 0.5:
        return []
    inside = Counter(t for i in rows for t in library.tokens[i])
    outside = Counter(t for i in base for t in library.tokens[i])
    floor = max(5, int(len(rows) * 0.002))
    lift = {w: (c / len(rows)) / (outside[w] / len(base)) for w, c in inside.items()
            if c >= floor and outside[w] and _used(library, w)}
    return sorted((w for w in lift if lift[w] >= 2), key=lambda w: (-lift[w] * math.log(inside[w]), w))[:most]


PROPOSE = '''Which words would short photo captions use for the photos that belong in this film: the
subject, its kinds, its parts, and what is done to it or with it over the film? Plain single
words. Return JSON.'''

CORE = '''Of these words, which name what must be the main subject of a photo for it to belong in this
film? relations says which words are a part or a kind of the subject: a photo of a part or a kind
of the subject is a photo of the subject. The others may appear in a photo that belongs, but
cannot make a photo belong on their own. Pick one to six. Return JSON.'''


def near_phrases(library, rows, heads, most=30):
    """How the owner's captions name things around the subject words: 'toy car', 'car seat'."""
    around = Counter()
    for i in sorted(rows):
        toks = re.findall(r"[a-z]+", (library.rows[i].get("caption") or "").lower())
        seen = set()
        for k, t in enumerate(toks):
            if t in heads or t.rstrip("s") in heads:
                before = [w for w in toks[max(0, k - 2):k] if w not in ARTICLES]
                if before and before[-1] not in GLUE:
                    seen.add(f"{before[-1]} {t}")
                if k + 1 < len(toks) and toks[k + 1] not in GLUE:
                    seen.add(f"{t} {toks[k + 1]}")
        around.update(seen)
    return [p for p, c in sorted(around.items(), key=lambda x: (-x[1], x[0])) if c >= 2][:most], around


def known_names():
    path = Path.home() / ".immich-memories/people.yaml"
    people = ((yaml.safe_load(path.read_text()) or {}).get("people") or []) if path.exists() else []
    people = people.values() if isinstance(people, dict) else people
    return [v.get("name") for v in people if isinstance(v, dict) and v.get("name")]


def build_subject(reader, key, brief, library, spec, rows):
    """What the photos show, chosen by Gemma from candidates the lexicon and the library offer."""
    # Who someone is is the people filter's job (faces); a name is never a subject word.
    names = {w for n in known_names() for w in re.findall(r"[a-z]+", n.lower())}
    seeds = [x.lower() for x in spec["seeds"] if not set(re.findall(r"[a-z]+", x.lower())) <= names]
    if not seeds:
        seeds = [w for w in re.findall(r"[a-z]+", brief.lower()) if w not in names][:1]
    heads = {re.findall(r"[a-z]+", x)[-1] for x in seeds if re.findall(r"[a-z]+", x)}
    with_seed = {i for i in rows if heads & library.tokens[i] or {h + "s" for h in heads} & library.tokens[i]}
    proposed = _ask(reader, "spec_propose", key, PROPOSE, {"owner_request": brief, "subject": seeds},
                    _schema(words={"type": "array", "items": {"type": "string", "maxLength": 30}, "maxItems": 15})
                    ).get("words") or []
    grounded = [w.lower() for w in proposed if _used(library, w.lower(), 5) and w.lower() not in names]
    related = lexicon(library, seeds)
    offered = [w for w in dict.fromkeys(seeds + grounded + list(related) + lifted(library, with_seed, rows)
                                        + lifted(library, rows)) if w not in names][:60]
    spec["sources"] = {"proposed": grounded, "lexicon": list(related),
                       "with_the_subject": lifted(library, with_seed, rows), "these_photos": lifted(library, rows)}
    picked = _ask(reader, "spec_pick_shows", key, PICK_SHOWS, {"owner_request": brief, "candidates": offered},
                  _schema(shows={"type": "array", "items": {"type": "string", "enum": offered or [""]}, "maxItems": 20}),
                  400).get("shows") or []
    shows = list(dict.fromkeys(seeds + [w for w in picked if w]))
    heads = {w for x in seeds for w in re.findall(r"[a-z]+", x)[-1:]}
    near, counts = near_phrases(library, rows, heads)
    not_this = _ask(reader, "spec_pick_not", key, PICK_NOT, {"owner_request": brief,
                    "phrases": [f"{p} ({counts[p]})" for p in near]},
                    _schema(not_this={"type": "array", "items": {"type": "string", "enum": near or [""]}, "maxItems": 15}),
                    400).get("not_this") or [] if near else []
    not_this = [x for x in not_this if x]
    # Gemma decides which words make a photo belong; the rest only widen the search.
    relations = {w: related[w] for w in shows if w in related}
    core = [w for w in _ask(reader, "spec_core", key, CORE, {"owner_request": brief, "words": shows,
                                                             "relations": relations},
                            _schema(core={"type": "array", "items": {"type": "string", "enum": shows or [""]}, "maxItems": 6})
                            ).get("core") or [] if w] or seeds or [brief]
    # Logic, not judgement: once Gemma names the subject, its parts and kinds are the subject too.
    from nltk.corpus import wordnet as wn

    def base(word):
        return wn.morphy(word, wn.NOUN) or word

    heads_of_core = {base(re.findall(r"[a-z]+", c)[-1]) for c in core if re.findall(r"[a-z]+", c)}
    extent = [w for w in shows if w not in core and relations.get(w, "").split(" of ")[-1] in heads_of_core]
    question = "Is the main subject of this photo " + " or ".join(core) + (
        " (or one of its parts or kinds: " + ", ".join(extent[:10]) + ")" if extent else "") + "?"
    core = core + extent
    if not_this:
        question += " (Not " + " or ".join(not_this[:6]) + ".)"
    also = [w for w in shows if w not in core]
    spec |= {"offered": offered, "shows": shows, "core": core, "not_this": not_this, "question": question,
             "meaning": "Main subject: " + ", ".join(core) + "." + (" It may also show: " + ", ".join(also) + "." if also else "")
             + (" Does not belong: " + ", ".join(not_this) + "." if not_this else ""),
             "caption_words": shows}
    return spec


def show(spec):
    """The translation as the owner reads it."""
    w = spec["where"]
    lines = [f'"{spec["english"]}"',
             f'  people        {", ".join(spec["people"]) or "anyone"}'
             + (" (faces recognised, per episode)" if spec["people_must_appear"] else ""),
             f'  when          {spec["when"]["from"] or "any time"} → {spec["when"]["to"] or "open"}'
             + (f' ({spec["span"]})' if spec.get("span") else ""),
             f'  where         {w["said"].split(":")[0]}',
             f'  text in photo {", ".join(spec["text_in_photo"]) or "none"}',
             f'  offered       {"; ".join(k + ": " + ", ".join(v) for k, v in spec.get("sources", {}).items() if v)}',
             f'  main subject  {", ".join(spec["core"]) or "-"}',
             f'  also finds    {", ".join(w for w in spec["shows"] if w not in spec["core"]) or "-"}',
             f'  not this      {", ".join(spec["not_this"]) or "-"}',
             f'  question      {spec["question"]}',
             f'  caption words {", ".join(spec["caption_words"])}',
             f'  shape         {spec["shape"]}']
    return "\n".join(lines)


if __name__ == "__main__":
    print(json.dumps(SHAPES))
