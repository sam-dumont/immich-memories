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
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

import yaml
from pathlib import Path

from discovery import GLUE
from experiment_data import ROOT

# The owner's house, measured: 19,298 pictures since 2016 lie within 50 m of it, 19,491 within
# 200 m, then the street starts (20,848 at 1 km, 29,450 at the trip detector's 10 km).
AT_HOME_KM = 0.15
INFERRED_HOME_KM = 0.3
PHOTOGRAPHED_WITHIN_KM = 0.3  # owner 09-28: 500 m is a lot
ARTICLES = {"a", "an", "the", "some", "two", "three", "several", "his", "her", "their", "its"}
SHAPES = ["one moment or event", "along the years", "how something changed over time",
          "first times", "a collection of one kind of thing"]


def _schema(**props):
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def infer_homes(library, assets):
    """Where the owner lived, from the library alone: each year's ~200 m cell with the most photo
    days, when it holds at least a fifth of that year's photo days; a new home starts when that
    cell moves more than 300 m. The owner's homes.yaml, when there is one, wins."""
    days = defaultdict(lambda: defaultdict(set))
    points = defaultdict(list)
    for r in library.rows:
        a = assets.get(r["asset_id"])
        if not a:
            continue
        lat, lon = a.exif_info.latitude, a.exif_info.longitude
        cell = (round(lat / 0.002), round(lon / 0.002))
        days[r["taken_at"][:4]][cell].add(r["taken_at"][:10])
        points[cell].append((lat, lon))
    out = []
    for year in sorted(days):
        cell, held = max(days[year].items(), key=lambda kv: (len(kv[1]), kv[0]))
        if len(held) < max(10, 0.2 * len(set().union(*days[year].values()))):
            continue
        where = tuple(sorted(x)[len(x) // 2] for x in zip(*points[cell]))
        if out and km((out[-1]["lat"], out[-1]["lon"]), where) <= 0.3:
            continue
        out.append({"name": f"home {len(out) + 1}", "lat": where[0], "lon": where[1],
                    "since": min(held) if out else f"{year}-01-01", "source": "inferred"})
    return out


def homes(library, assets):
    """The homes list with each one's end date and the area name Immich gives its pictures."""
    path = ROOT / "homes.yaml"
    listed = sorted((yaml.safe_load(path.read_text()) or {}).get("homes") or [], key=lambda h: str(h["since"])) \
        if path.exists() else []
    listed = listed or infer_homes(library, assets)
    out = []
    for n, h in enumerate(listed):
        until = str(listed[n + 1]["since"]) if n + 1 < len(listed) else None
        where = (h["lat"], h["lon"])
        points = [where]
        # Where the phone put the photos taken there: indoors GPS settles away from the address pin
        # (the owner's pin was 180 m from the photos of that home, 09-28). The densest ~100 m cell of
        # photo days within 300 m during the stay joins the home's points.
        days, near = {}, {}
        for r in library.rows:
            a = assets.get(r["asset_id"])
            if not a or not (str(h["since"]) <= r["taken_at"][:10] < (until or "9999")):
                continue
            spot = (a.exif_info.latitude, a.exif_info.longitude)
            if km(where, spot) <= PHOTOGRAPHED_WITHIN_KM:
                cell = (round(spot[0] / 0.001), round(spot[1] / 0.001))
                days.setdefault(cell, set()).add(r["taken_at"][:10])
                near.setdefault(cell, []).append(spot)
        if days:
            cell = max(days, key=lambda c: (len(days[c]), c))
            if len(days[cell]) >= 3:
                spots = near[cell]
                points.append(tuple(sorted(x)[len(x) // 2] for x in zip(*spots)))
        areas = Counter(r.get("city") for r in library.rows
                        if (a := assets.get(r["asset_id"]))
                        and min(km(p, (a.exif_info.latitude, a.exif_info.longitude)) for p in points) <= AT_HOME_KM)
        # An inferred home is a ~200 m grid cell's estimate: 150 m missed photos 260 m from it (09-28).
        radius = AT_HOME_KM if h.get("source") == "confirmed" else INFERRED_HOME_KM
        out.append({"name": h.get("name") or f"home {n + 1}", "lat": h["lat"], "lon": h["lon"], "points": points,
                    "since": str(h["since"]), "until": until, "radius": radius,
                    "area": [c for c, _ in areas.most_common(2) if c]})
    return out


def where_options(lived):
    # Each option says what it means, as a semantic layer describes its fields: Gemma picks by meaning.
    options = {"anywhere: the request does not tie the photos to a place": ("any", None)}
    if lived:
        options["at home, wherever the owner lived when the photo was taken: what belongs to the owner's "
                "household and moves with them (their pets, life at home)"] = ("home_at_time", None)
        options["near home: around where the owner lived at the time, the neighbourhood and town, not "
                "only the house"] = ("near_home", None)
    for h in lived:
        area = f", the area Immich calls {' / '.join(h['area'])}" if h["area"] else ""
        options[f"at the {h['name']} home only ({h['since'][:4]} to {h['until'][:4] if h['until'] else 'now'}{area}): "
                "that house or flat itself, or what happened in it"] = ("home", h["name"])
    options["away from home: only when the request says holidays, trips or travel"] = ("trips", None)
    return options


def at_home_rows(library, assets, lived, which=None, radius=AT_HOME_KM, require_gps=False):
    """Rows taken at a home: `which` names one; None means the home valid on the photo's date."""
    out = set()
    for i, r in enumerate(library.rows):
        a = assets.get(r["asset_id"])
        if not a:
            # No GPS is no evidence of elsewhere when the place only frames the subject (a pet at
            # home): the photo stays. When the subject IS a place (the spec's subject_kind), a photo
            # must show it was there: a house film admitted a Thai house and a stranger's pool
            # house without GPS (09-28).
            if not require_gps:
                out.add(i)
            continue
        day = r["taken_at"][:10]
        if which:
            candidates = [h for h in lived if h["name"] == which]
        else:
            candidates = [h for h in lived if h["since"] <= day and (h["until"] is None or day < h["until"])][-1:]
        spot = (a.exif_info.latitude, a.exif_info.longitude)
        if any(km(p, spot) <= max(radius, h.get("radius", 0)) for h in candidates for p in h.get("points") or [(h["lat"], h["lon"])]):
            out.add(i)
    return out


WHERE = '''Where were the photos this request asks for taken? Pick the option whose description fits
the request best. Reason first. Return JSON.'''

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

ALONGSIDE = '''These words come from the owner's captions that show the film's main subject. Which of
them describe photos that belong in this film, given the film's shape? For a film of how
something changed over time, that includes the subject being worked on or changed, and its state
before and after. Return JSON.'''

SAME_AS = '''Which of these words name the main subject itself too: a young one of it, another name for
it, or a kind of it? Only words that do; none when none does. Return JSON.'''

LEAVE_OUT = '''Which of these phrases from the request name what the owner asks to leave out of the film?
None when the request excludes nothing. Return JSON.'''

SPAN = '''This film is about one moment or event that starts on date_from. How long after it do its
photos run? Pick one. Return JSON.'''
SPANS = {"one day": 0, "one week": 6, "one month": 30, "three months": 91}

SHAPE = '''What shape of film does the request ask for? Pick one. Return JSON.'''

KIND = '''What kind of thing is the main subject of the photos this request asks for? A place is
somewhere a person can be: a building or part of one, an outdoor area, a view. Pick one. Reason
first. Return JSON.'''
KINDS = ["a place", "a person", "an animal", "a thing", "an activity or event"]

ONE = '''Does the request follow one particular individual of its main subject (the owner's own, the
same one across the photos) or any of that kind? Pick one. Reason first. Return JSON.'''
ONES = ["one particular individual", "any of that kind"]

FILTERS = '''Give the date range the photos were taken in (YYYY-MM-DD, or null for no bound), and
whether the listed people's faces must be recognised in each photo. Use the facts given (people's
birth dates, when the owner moved into each home, years written in the request, today's date, and
the film's shape). A film of one moment or event gets only the few days or weeks that moment
covers; a request that runs on ("since", "along the years") leaves the end open. Return JSON.'''


def _ask(reader, stage, key, prompt, data, schema, tokens=300):
    return reader.ask(stage, key, prompt, data, lambda a: None, tokens, schema=schema) or {}


def _vote(reader, stage, key, prompt, data, field, options, most, tokens=300):
    """A pick-list answer asked three times with the options in three orders; a word needs two
    votes. One answer is a coin toss at 4B: the same request once named "black cat", once "cat"
    and "dog" as another name for it, after the candidate list shifted (09-28)."""
    if not options:
        return []
    votes = Counter()
    for n, order in enumerate([options, options[::-1], options[1:] + options[:1]]):
        got = _ask(reader, stage, f"{key}:v{n}", prompt, data | {field + "_options": order},
                   _schema(**{field: {"type": "array", "items": {"type": "string", "enum": order},
                                      "maxItems": most}}), tokens).get(field) or []
        votes.update({w for w in got if w in options})
    return [w for w in options if votes[w] >= 2]


def _choose(reader, stage, key, prompt, data, options, tokens=500):
    """One choice asked three times in three option orders; the majority wins, else the first option."""
    votes = Counter()
    for n, order in enumerate([options, options[::-1], options[1:] + options[:1]]):
        got = _ask(reader, stage, f"{key}:c{n}", prompt, data | {"options": order},
                   _schema(reason={"type": "string", "maxLength": 200}, choice={"type": "string", "enum": order}),
                   tokens).get("choice")
        if got in options:
            votes[got] += 1
    top = votes.most_common(1)
    return (top[0][0] if top and top[0][1] >= 2 else options[0]), dict(votes)


def stated_phrase(brief, word):
    """The request's own wording of a subject noun with its quality ("Black cat" -> "black cat")."""
    from nltk.corpus import wordnet as wn

    head = wn.morphy(word.split()[-1], wn.NOUN) or word.split()[-1]
    toks = re.findall(r"[a-z]+", brief.lower())
    for k in range(1, len(toks)):
        if (wn.morphy(toks[k], wn.NOUN) or toks[k]) == head and toks[k - 1] not in GLUE | ARTICLES \
                and wn.synsets(toks[k - 1], pos=wn.ADJ):
            return f"{toks[k - 1]} {toks[k]}"
    return word


def build_spec(reader, key, brief, library, people_named, lived, years):
    """people_named: the people the request is about (already linked); returns the spec dict."""
    options = where_options(lived)
    # One answer is a coin toss at 4B: asked three times with the options in three orders, the
    # majority wins; three different answers fall back to the widest place (loses precision only).
    names = list(options)
    orders = [names, names[::-1], names[1:] + names[:1]]
    answers = []
    for n, order in enumerate(orders):
        got = _ask(reader, "spec_where", f"{key}:o{n}", WHERE, {"owner_request": brief, "options": order},
                   _schema(reason={"type": "string", "maxLength": 200}, where={"type": "string", "enum": order}),
                   700)  # the server does not enforce maxLength: reasons ran past 300 tokens
        if got.get("where") in options:
            answers.append(got)
    votes = Counter(a["where"] for a in answers)
    top = votes.most_common(1)
    where_text = top[0][0] if top and top[0][1] >= 2 else names[0]
    where = next((a for a in answers if a["where"] == where_text), {})
    request_words = sorted({w for w in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", brief)})
    text = _ask(reader, "spec_text", key, TEXT, {"owner_request": brief},
                _schema(words={"type": "array", "items": {"type": "string", "enum": request_words or [""]}, "maxItems": 3}))
    shows = [x.strip() for x in _ask(reader, "spec_shows", key, SHOWS, {"owner_request": brief},
             _schema(shows={"type": "array", "items": {"type": "string", "maxLength": 50}, "maxItems": 10})
             ).get("shows") or [] if x.strip()]
    # What the subject is decides how identity is proven: a place by GPS, a person by faces, one
    # particular animal or thing by a sameness check against reference photos (owner 09-28).
    kind_of, kind_votes = _choose(reader, "spec_kind", key, KIND, {"owner_request": brief, "subject": shows}, KINDS)
    one, one_votes = (_choose(reader, "spec_one", key, ONE, {"owner_request": brief, "subject": shows}, ONES)
                      if kind_of in {"an animal", "a thing"} else (None, {}))
    shape, shape_votes = _choose(reader, "spec_shape", key, SHAPE, {"owner_request": brief}, SHAPES)
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
            "where": {"said": where_text, "kind": kind, "home": home, "why": (where.get("reason") or "")[:200],
                      "votes": dict(votes)},
            "text_in_photo": [w for w in text.get("words") or [] if w],
            "seeds": shows, "span": span,
            "subject_kind": {"an activity or event": "activity"}.get(kind_of, kind_of.split()[-1]),
            "one_particular": one == ONES[0],
            "kind_votes": {"kind": kind_votes, "one": one_votes, "shape": shape_votes},
            "shape": shape}


def _used(library, word, at_least=None):
    # Scaled to the library: 10 uses in 76k captions, 2 in a few thousand.
    floor = at_least if at_least is not None else max(2, len(library.rows) // 8000)
    return "_" not in word and len(library.posts.get(word, ())) >= floor


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
    floor = max(3, int(len(rows) * 0.002))
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
    grounded = [w.lower() for w in proposed if _used(library, w.lower(), max(2, len(library.rows) // 15000))
                and w.lower() not in names]
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
    # What the owner says to leave out, picked from the request's own phrases.
    # Only what follows a negation can be left out: asked over the whole request, E4B picked the
    # subject itself ("garden" out of "our garden").
    negated = re.findall(r"\b(?:not|no|without|except|excluding|but not)\b([^.;!?]*)", brief.lower())
    toks_of = [re.findall(r"[a-z][a-z'\-]*", span) for span in negated]
    grams = list(dict.fromkeys(" ".join(t[i:i + n]) for t in toks_of for n in (1, 2, 3) for i in range(len(t) - n + 1)
                               if not set(t[i:i + n]) <= GLUE | {"please", "or", "and"}))[:40]
    said = _ask(reader, "spec_leave_out", key, LEAVE_OUT, {"owner_request": brief, "phrases": grams},
                _schema(leave_out={"type": "array", "items": {"type": "string", "enum": grams or [""]}, "maxItems": 4})
                ).get("leave_out") or [] if grams else []
    not_this = list(dict.fromkeys([x for x in said if x] + not_this))
    # Gemma decides which words make a photo belong; the rest only widen the search.
    relations = {w: related[w] for w in shows if w in related}
    core = _vote(reader, "spec_core", key, CORE, {"owner_request": brief, "relations": relations},
                 "core", shows, 6) or seeds or [brief]
    # A quality the request states stays ("our cat ... Black cat." -> "black cat", whatever Gemma dropped).
    core = list(dict.fromkeys(stated_phrase(brief, c) for c in core))
    # Logic, not judgement: once Gemma names the subject, its parts and kinds are the subject too.
    from nltk.corpus import wordnet as wn

    def base(word):
        return wn.morphy(word, wn.NOUN) or word

    heads_of_core = {base(re.findall(r"[a-z]+", c)[-1]) for c in core if re.findall(r"[a-z]+", c)}
    extent = [w for w in shows if w not in core and relations.get(w, "").split(" of ")[-1] in heads_of_core]
    # The words captions use alongside the chosen subject, offered back: how a change shows up
    # (paint, ladder, peeling) is in the owner's captions, not in the request.
    core_words = {w for c in core + extent for w in re.findall(r"[a-z]+", c)}
    with_core = {i for i in rows if core_words & library.tokens[i]}
    near_core = [w for w in lifted(library, with_core, rows, most=30) if w not in shows and w not in names]
    alongside = _vote(reader, "spec_alongside", key, ALONGSIDE, {
        "owner_request": brief, "main_subject": core + extent, "film_shape": spec["shape"]},
        "words", near_core, 15)
    shows = list(dict.fromkeys(shows + alongside))
    # Other names for the subject itself (a kitten is the cat, 09-28): Gemma picks them; the core's
    # stated qualities carry over ("black cat" + "kitten" -> "black kitten").
    # Candidates: the other words, and what the filtered photos' captions put in the subject slot
    # ("A black kitten is..."): a subject's other names sit where the subject sits.
    from cascade import subject_head

    slot = Counter(h for i in rows if (h := subject_head(library.rows[i].get("caption"))))
    slot_words = [w for w, n in slot.most_common(40) if n >= 3 and w not in names]
    others = list(dict.fromkeys(w for w in shows + slot_words if w not in core and w not in extent))[:50]
    same = _vote(reader, "spec_same_as", key, SAME_AS, {"owner_request": brief, "main_subject": core},
                 "same", others, 6)
    # The qualities come from the main phrase only: a bare part ("paw") would make a bare "kitten".
    main = next((c for c in core if len(c.split()) > 1), core[0])
    qualities = re.findall(r"[a-z]+", main.lower())[:-1]
    extent += [p for w in same if (p := " ".join(qualities + [w])) not in core + extent]
    question = "Is the main subject of this photo " + " or ".join(core) + (
        " (or one of its parts or kinds: " + ", ".join(extent[:10]) + ")" if extent else "") + "?"
    core = core + extent
    if not_this:
        question += " (Not " + " or ".join(not_this[:6]) + ".)"
    also = [w for w in shows if w not in core]
    spec |= {"offered": offered, "alongside": alongside, "shows": shows, "core": core, "not_this": not_this, "question": question,
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
             f'  alongside     {", ".join(spec.get("alongside") or []) or "-"}',
             f'  not this      {", ".join(spec["not_this"]) or "-"}',
             f'  question      {spec["question"]}',
             f'  caption words {", ".join(spec["caption_words"])}',
             f'  shape         {spec["shape"]}',
             f'  subject kind  {spec.get("subject_kind")}' + (" (photos need GPS)" if spec.get("subject_kind") == "place" else "")
             + (", one particular: checked against reference photos" if spec.get("one_particular") else "")]
    return "\n".join(lines)


if __name__ == "__main__":
    print(json.dumps(SHAPES))
