"""Cheaper machinery in front of Gemma, each part calibrated per request (owner 09-28). The default
and only path: no switch (owner ruling, "no gate, this is how we lose stuff").

- Captions: a caption whose subject (before its verb) is a main-subject word belongs, free
  ("A black cat is sleeping...", "A car's dashboard with..."): measured 92-100% precise on the
  owner's labels where Gemma's caption check agreed with it only 69% of the time.
- Photos: the stack's own captioner (SmolVLM-500M, ~0.7 s a photo against ~5.6 s) answers the
  same yes/no question. Both answer the first photos; SmolVLM answers the rest only when they agree
  on at least AGREE of them.
Nothing here knows a request: the sample decides, every time.
"""

import hashlib
import json
import re

import httpx

from experiment_data import ROOT, save

AGREE = 0.9
SMOL_SAMPLE = 24
# English grammar, not meaning: the first verb or preposition ends a caption's subject.
SUBJECT_ENDS = re.compile(
    r"\b(is|are|was|were|sits|sit|sitting|stands|standing|lies|lying|lays|laying|rests|resting|with|on|in|at|"
    r"near|next|inside|under|behind|beside|by|against|holding|holds|filled|displays|displayed|shows|showing|"
    r"parked|driving|riding|walking|covered|surrounded|featuring|that|which|while|as|from|into|through)\b")


def _stem(word):
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def grammar_says_subject(caption, core, not_this=()):
    """True when a main-subject phrase names the caption's grammatical subject: every word of the
    phrase ("black cat" needs both) before the first verb form ("A man wearing a black t-shirt"
    is a man, not a black cat; 09-28, the engine's picks showed it)."""
    text = (caption or "").lower()
    if not text or any(p.lower() in text for p in not_this or ()):
        return False
    end = SUBJECT_ENDS.search(text)
    head = text[:end.start()] if end else text
    verb = re.search(r"\b[a-z]+ing\b", head)
    head = head[:verb.start()] if verb else head
    subject = {_stem(w) for w in re.findall(r"[a-z]+", head)}
    return any((words := {_stem(w) for w in re.findall(r"[a-z]+", phrase.lower())}) and words <= subject
               for phrase in core)


def _captioner(config):
    base = config.editorial.preparation.caption_base_url.rstrip("/")
    models = httpx.get(base + "/models", timeout=10, trust_env=False).json()["data"]
    return base, models[0]["id"]


_ENDPOINT = {}


def smol_yes(config, question, asset_id, preview):
    """The captioner's yes/no on one photo; None when it gives no usable answer. Cached."""
    if "base" not in _ENDPOINT:
        _ENDPOINT["base"], _ENDPOINT["model"] = _captioner(config)
    cache = ROOT / "looks-smol"
    cache.mkdir(exist_ok=True)
    path = cache / (hashlib.sha256((_ENDPOINT["model"] + question + asset_id).encode()).hexdigest()[:24] + ".json")
    if path.exists():
        return json.loads(path.read_text()).get("yes")
    try:
        image = preview(config, asset_id)
    except httpx.HTTPError:
        return None  # Immich serves no preview for it (a deleted or unprocessed forward)
    body = {"model": _ENDPOINT["model"], "max_tokens": 3, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image}},
                {"type": "text", "text": question + " Answer yes or no."}]}]}
    try:
        reply = httpx.post(_ENDPOINT["base"] + "/chat/completions", json=body, timeout=120, trust_env=False).json()
        text = reply["choices"][0]["message"]["content"].strip().lower()
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None
    answer = True if text.startswith("yes") else False if text.startswith("no") else None
    save(path, {"yes": answer, "raw": text})
    return answer




# ---- The light pool: the free tier first, Gemma only where a period is thin, photos only where no
# caption can speak (owner 09-28: the free tier alone was 92-100% precise on the pet, the
# landscapes and the birth, against the owner's labels).

HEADS = ("doc_docling", "activity")
MIN_PER_PERIOD = 12   # enough for the engine to choose from in a period; the pet's 300 s film used ~4 a year
READ_PER_PERIOD = 96  # captions Gemma reads at most in one thin period (four calls)
LOOK_PER_PERIOD = 24  # photos looked at at most in one thin period


def banked_heads(bank, asset_ids):
    """The small heads preparation already ran, read from the annotation store: free."""
    import sqlite3

    out = {}
    wanted = list(set(asset_ids))
    with sqlite3.connect(f"file:{bank}?mode=ro", uri=True) as db:
        for start in range(0, len(wanted), 900):
            part = wanted[start:start + 900]
            rows = db.execute(
                f"SELECT asset_id, head, label FROM head_facts WHERE head IN ({','.join('?' * len(HEADS))}) "
                f"AND asset_id IN ({','.join('?' * len(part))}) ORDER BY decided_at", (*HEADS, *part))
            for asset_id, head, label in rows:
                out.setdefault(asset_id, {})[head] = label
    return out


def period_of(row, shape):
    return row["taken_at"][:10] if shape == "one moment or event" else row["taken_at"][:4]


def fill_pool(library, pool, core, not_this, shape, anchors, captionless, read, look=None, place_words=()):
    """The free tier (captions whose subject is a main-subject word) is the pool; a thin period
    (fewer than MIN_PER_PERIOD) gets Gemma on its other captions, core word first, then a look at
    what no caption can settle. read(refs) -> decisions; look(refs) -> (confirmed, log).
    Returns (kept, log, stats, stages)."""
    from collections import defaultdict

    caption = lambda i: library.rows[i].get("caption") or ""  # noqa: E731
    captioned = {i for i in pool if caption(i) and not library.rows[i].get("uncaptioned")}
    free = {i for i in captioned if grammar_says_subject(caption(i), core, not_this)}
    if place_words:
        # A place subject is proven by GPS; its caption only has to show the place or its change:
        # at the house, "a ladder leaning against a wall" with "renovation" or "peeling" is the house
        # changing (146 such works photos were left out when only the caption's subject counted).
        wanted = {w for w in place_words}
        # ...unless the caption's subject is a being: "a woman standing in a bathroom with white
        # tiles" is about her (120 of 535 such photos entered through a room word, 09-28).
        free |= {i for i in captioned if not any(p.lower() in caption(i).lower() for p in not_this)
                 and wanted & set(re.findall(r"[a-z]+", caption(i).lower()))
                 and not _is_being(subject_head(caption(i)))}
    wanted = {_stem(w) for phrase in core for w in re.findall(r"[a-z]+", phrase.lower())}
    periods = defaultdict(list)
    for i in pool:
        periods[period_of(library.rows[i], shape)].append(i)
    said_yes, unsure, read_refs = set(), set(), set()
    # A thin period stays thin ("short beats a guess"): Gemma's yeses there were good 1 in 5, 0 in 9
    # and 0 in 5 on the owner's labels (09-28). It reads only when the request has almost no free
    # tier at all (the subject is never a caption's subject: "breastfeeding").
    for _, refs in sorted(periods.items()) if len(free) < MIN_PER_PERIOD else ():
        have = len(free & set(refs))
        if have >= MIN_PER_PERIOD:
            continue
        rest = sorted((i for i in refs if i in captioned and i not in free),
                      key=lambda i: (not wanted & {_stem(w) for w in re.findall(r"[a-z]+", caption(i).lower())},
                                     library.rows[i]["taken_at"]))[:READ_PER_PERIOD]
        for start in range(0, len(rest), 24):
            part = rest[start:start + 24]
            decided = read(part)
            read_refs |= set(part)
            said_yes |= {d["ref"] for d in decided if d["decision"] == "match"}
            unsure |= {d["ref"] for d in decided if d["decision"] == "unknown"}
            if have + len(said_yes & set(refs)) >= MIN_PER_PERIOD:
                break
    to_look = set()
    for _, refs in periods.items():
        if len((free | said_yes) & set(refs)) >= MIN_PER_PERIOD:
            continue
        open_ = [i for i in refs if i in captionless or i in unsure or (i in anchors and i not in free | said_yes)]
        to_look |= set(sorted(open_, key=lambda i: (i not in anchors, library.rows[i]["taken_at"]))[:LOOK_PER_PERIOD])
    seen, log = look(to_look) if look and to_look else (set(), [])
    kept = free | said_yes | set(seen)
    stats = {"free": len(free), "periods": len(periods),
             "thin_periods": sum(len(free & set(r)) < MIN_PER_PERIOD for r in periods.values()),
             "captions_read": len(read_refs), "caption_yes": len(said_yes), "looked": len(to_look) if look else 0,
             "photo_yes": len(seen)}
    stages = {"free": free, "caption_read": read_refs, "caption_yes": said_yes, "caption_unsure": unsure,
              "to_look": to_look}
    return sorted(kept, key=lambda i: library.rows[i]["taken_at"]), log, stats, stages


def fewer_poses(library, kept, heads, shape, per=8):
    """At most one posed photo per `per` others in each period, for a subject that is not a person
    (one per four still left the engine picking 38% posed, 09-28):
    the engine favours people and picked twice the pool's share of poses (41% of 21%, 09-28)."""
    from collections import defaultdict

    posing = lambda i: heads.get(library.rows[i]["asset_id"], {}).get("activity") == "posing"  # noqa: E731
    periods = defaultdict(list)
    for i in kept:
        periods[period_of(library.rows[i], shape)].append(i)
    out = []
    for refs in periods.values():
        posed = sorted((i for i in refs if posing(i)), key=lambda i: library.rows[i]["taken_at"])
        others = [i for i in refs if not posing(i)]
        room = max(1, len(others) // per)
        out += others + posed[:: max(1, len(posed) // room)][:room]
    return sorted(out, key=lambda i: library.rows[i]["taken_at"])


def subject_head(caption):
    """The last word of a caption's subject ("A small black kitten is..." -> "kitten")."""
    text = (caption or "").lower()
    end = SUBJECT_ENDS.search(text)
    head = text[:end.start()] if end else text
    verb = re.search(r"\b[a-z]+ing\b", head)
    words = re.findall(r"[a-z]+", head[:verb.start()] if verb else head)
    return words[-1] if words else None


def balance_years(library, kept):
    """For an 'along the years' film: a year holding more than the median year is thinned, evenly
    over its dates, to the median, so no year can bury another (the first year got 1 pick of 52
    from a pool holding 61 of its photos, 09-28)."""
    from collections import defaultdict

    years = defaultdict(list)
    for i in sorted(kept, key=lambda i: library.rows[i]["taken_at"]):
        years[library.rows[i]["taken_at"][:4]].append(i)
    sizes = sorted(len(v) for v in years.values())
    cap = max(MIN_PER_PERIOD * 2, sizes[len(sizes) // 2]) if sizes else 0
    out = []
    for refs in years.values():
        out += refs if len(refs) <= cap else [refs[round(k * len(refs) / cap)] for k in range(cap)]
    return sorted(out, key=lambda i: library.rows[i]["taken_at"])


def _is_being(word):
    """Whether a caption's subject word names a person or an animal (WordNet, main noun sense)."""
    if not word:
        return False
    from nltk.corpus import wordnet as wn

    senses = wn.synsets(wn.morphy(word, wn.NOUN) or word, pos=wn.NOUN)[:1]
    beings = {"person.n.01", "animal.n.01"}
    return any(h.name() in beings for s in senses for path in s.hypernym_paths() for h in path)


SAME = '''The first {n} photos show the owner's own {subject}. Is the {subject} in the last photo the same
individual? Answer "different" only when it clearly is another one (other colour, markings, size or
shape); "cannot_tell" when the photo does not let you decide. Reason first. Return JSON.'''


def same_individual(library, kept, at_home, subject, ask, preview, config, key, refs_wanted=4):
    """For one particular animal or thing (owner 09-28): photos away from home are checked, one per
    moment, against reference photos taken at home; a moment leaves only on a clear "different".
    ask(text, images, schema) -> answer. Returns (kept, report)."""
    import hashlib

    from experiment_data import ROOT, save

    home = sorted((i for i in kept if i in at_home), key=lambda i: library.rows[i]["taken_at"])
    if len(home) < 2:
        return kept, {"checked": 0, "why": "too few reference photos at home"}
    refs = [home[round(k * (len(home) - 1) / (refs_wanted - 1))] for k in range(refs_wanted)] if len(home) >= refs_wanted else home
    away = [i for i in kept if i not in at_home]
    by_moment = {}
    for i in sorted(away, key=lambda i: library.rows[i]["taken_at"]):
        t = library.rows[i]["taken_at"][:10]  # one check per day away: per hour cost 9 min for 128 checks (09-28)
        by_moment.setdefault(t, []).append(i)
    images = [preview(config, library.rows[i]["asset_id"]) for i in refs]
    schema = {"type": "object", "additionalProperties": False, "required": ["reason", "same"],
              "properties": {"reason": {"type": "string", "maxLength": 200},
                             "same": {"type": "string", "enum": ["same", "different", "cannot_tell"]}}}
    cache = ROOT / "same-as"
    cache.mkdir(exist_ok=True)
    dropped, answers = set(), {}
    text = SAME.format(n=len(refs), subject=subject)
    for moment, refs_here in by_moment.items():
        probe = refs_here[0]
        aid = library.rows[probe]["asset_id"]
        path = cache / (hashlib.sha256((text + "|".join(library.rows[i]["asset_id"] for i in refs) + aid).encode()).hexdigest()[:24] + ".json")
        if path.exists():
            answer = json.loads(path.read_text())
        else:
            try:
                answer = ask(text, images + [preview(config, aid)], schema)
            except Exception as exc:  # noqa: BLE001 - one unreadable photo keeps its moment
                answer = {"same": "cannot_tell", "reason": f"error: {exc}"[:200]}
            save(path, answer)
        answers[moment] = answer.get("same")
        if answer.get("same") == "different":
            dropped |= set(refs_here)
    report = {"references": [library.rows[i]["asset_id"] for i in refs], "moments_checked": len(by_moment),
              "answers": dict(__import__("collections").Counter(answers.values())), "dropped": len(dropped)}
    return [i for i in kept if i not in dropped], report
