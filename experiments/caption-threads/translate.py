"""Semantic translation: a light sentence -> a plan over the existing generate surface.

The plan is small on purpose (a 4B model fills it): window, scope, subject, text to read,
exclusions, what no picture can prove. Everything after it is existing code: the product's
trip detection and home radius, the caption bank, Immich OCR, the E4B membership check,
then a normal date-window `generate` narrowed to the checked pictures with the thesis as its
written subject. Captions are the basis; OCR anchors are letters really in the photo.

usage (env as run.sh): python translate.py "<sentence>"   (FILM_DRY=1: plan and pool only)
"""

import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from experiment_data import ROOT, load_library, save
from immich_memories.analysis.editorial_home_radius import HOME_RADIUS_KM, home_of, near_home_of
from immich_memories.analysis.trip_detection import detect_trips
from immich_memories.analysis.llm_wire import openai_headers
from immich_memories.api.models import Asset, ExifInfo
from immich_memories.config import Config
from model_reader import Reader
from query import companion_terms, retrieve_plan, vocabulary
from workflow import choose_sources

def _list(desc, most=6):
    return {"type": "array", "items": {"type": "string"}, "maxItems": most, "description": desc}


def _schema(**props):
    # Every key required and every list capped: oMLX's enforced grammar stalls when the model
    # wants to stop before a required key, and optional keys get skipped (measured 09-27).
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


SUBJECT_SCHEMA = _schema(subject=_list("what must be visible, with any colour, size or kind the request states", 4))
SUBJECT = '''What must be visible in the photos this request asks for? Use plain words a photo
caption would use (caption_vocabulary), keeping any colour, size or kind the request states
("black cat", not "cat"). Return JSON.'''
COLOURS = set("black white grey gray brown red orange yellow green blue purple pink ginger golden silver".split())
FILLER_WORDS = set("a an the of in on at to for from with and or our my his her their your we i "
                   "me us it its this that these those pictures picture photos photo memory memories "
                   "create make show film video along years year over time all every best since anything something "
                   "everything nothing".split())


def parse_structure(brief, people, library):
    """Everything a pattern can answer, answered by patterns (dates, people, text, shape)."""
    low = brief.lower()
    names = {}
    for full in people:
        first = full.split()[0].lower()
        if re.search(rf"\b{re.escape(first)}\b", low) or full.lower() in low:
            names[full] = True
    words_in = re.findall(r"[a-zA-Z][a-zA-Z'\-]+", brief)
    known = set(library.posts)
    # Words no caption ever used and no dictionary would: candidates for letters in the photo.
    odd = [w for w in words_in if w.lower() not in FILLER_WORDS
           and not any(w.lower() == n.split()[0].lower() or w.lower().rstrip("'s") == n.split()[0].lower() for n in people)
           and len(w) > 3 and not wn_known(w)]
    places = {str(r.get(k) or "").lower() for r in library.rows[:: max(1, len(library.rows) // 20000)]
              for k in ("city", "region", "country")}
    excluded = " ".join(re.findall(r"\b(?:not|no|without|except)\s+([a-z][a-z \-]{2,40})", low))
    # "in X", "at X / Y": a place the sentence names, not letters to read in the photo.
    named_places = {w.lower() for m in re.findall(r"\b(?:in|at|near|from|around)\s+([^,.;]{2,40})", low)
                    for w in re.findall(r"[a-z]+", m)}
    odd = [w for w in odd if w.lower() not in places and w.lower() not in excluded
           and w.lower() not in named_places]
    thing = re.search(r"\b(?:our|my)\s+(?:own\s+)?([a-z]+)", low)
    excl = re.findall(r"\b(?:not|no|without|except)\s+(?:the\s+|any\s+)?([a-z][a-z \-]{2,40}?)(?=[,.;]|$| please)", low)
    stated = {"trips": r"\b(holiday|holidays|vacation|trip|trips|travel|travels|abroad|journey)\b",
              "home": r"\b(home|house|flat|apartment|our place|garden)\b"}
    scope = next((k for k, p in stated.items() if re.search(p, low)), "any")
    return {"people": list(names), "read_text": odd, "firsts": bool(re.search(r"\bfirsts?\b", low)),
            "same_thing": thing[1] if thing and thing[1] not in {"own", "first", "firsts"} else None,
            "exclusions": [e.strip() for e in excl], "scope": scope}


def wn_known(word):
    from nltk.corpus import wordnet as wn
    return bool(wn.synsets(word.lower()))


def ask_plan(reader, key, brief, context, library, people):
    plan = parse_structure(brief, people, library)
    answer = reader.ask("plan_subject", key, SUBJECT, {"owner_request": brief,
                        "caption_vocabulary": context["caption_vocabulary"]}, lambda a: None, 400,
                        schema=SUBJECT_SCHEMA)
    if answer is None:
        return None
    known = set(library.posts)
    subject = [s.lower() for s in answer["subject"]]
    # Qualifiers are words the sentence states AND the captions use; a place or a club name is not one.
    stated = set(re.findall(r"[a-z]+", brief.lower()))
    qualifiers = sorted({w for s in subject for w in s.split()
                         if w in stated and w in known and (w in COLOURS or len(s.split()) > 1)} - set(
                             w for s in subject for w in s.split()[-1:]))
    plan |= {"subject": subject, "qualifiers": qualifiers, "title": brief[:60], "unverifiable": [], "unmapped": []}
    plan["visual_questions"] = [f"Does the photo show {s}?" for s in subject[:2]]
    return plan


TRANSLATE = '''Translate the owner's request for a photo film into a search plan over their library.
- scope: "trips" when it is about holidays or travel away from home, "home" when it is about
  the owner's home, otherwise "any".
- subject: short phrases for what must be visible in the pictures, using words from
  caption_vocabulary where they fit. Empty when the request is only about a time or a place.
- read_text: words that would be written on something in the photos (a club, a brand, a sign),
  spelled as they would appear. Empty when nothing written is asked for.
- exclusions: what the owner wants left out.
- unverifiable: parts of the request no picture can prove (ownership, who drove, feelings).
- visual_questions: one to three yes/no questions someone looking at a photo would ask to
  decide whether it belongs, using only what the request says.
- same_thing: what single thing the film follows over time when the request is about one
  particular thing (a house, an animal, a car), else null.
- qualifiers: every colour, size, material or kind the request states about the subject.
- people: names from known_people the request is about, spelled exactly as listed.
- unmapped: anything in the request that no other field can hold.
- firsts: true when the owner asks for first times (the first time someone did or saw something).
Return JSON {"title":short plain title,"scope":"any|home|trips","subject":[phrases],
"read_text":[strings],"exclusions":[strings],"unverifiable":[strings],
"visual_questions":[strings],"same_thing":string or null,"people":[names],"firsts":boolean}.'''

THESIS = '''Write the thesis of a short film from the owner's request and the pictures found for
it (dates and captions, in order). Two to four plain sentences: what the film is about and how
it moves through time. Use only the owner's words and what the captions show; invent no names,
events or feelings. Return JSON {"thesis":string}.'''

EPISODE = timedelta(minutes=90)  # the product's episode gap (selection_source_groups)
PER_YEAR = 24                    # judge budget per year of a long window


def years_of(brief):
    """Dates are pattern work, not model work."""
    span = re.search(r"\b(19|20)(\d\d)\s*(?:-|–|to|until|through)\s*(19|20)(\d\d)\b", brief)
    if span:
        return int(span[1] + span[2]), int(span[3] + span[4])
    since = re.search(r"\b(?:since|from|after)\s+(?:\w+\s+){0,4}?((?:19|20)\d\d)\b", brief, re.I)
    single = re.findall(r"\b((?:19|20)\d\d)\b", brief)
    if since:
        return int(since[1]), None
    if len(single) == 1:
        return int(single[0]), int(single[0])
    return None, None


def bank_assets(library, bank):
    """The bank's GPS as product Assets, so the product's own trip detection runs unchanged."""
    with sqlite3.connect(f"file:{bank}?mode=ro", uri=True) as db:
        gps = {a: (la, lo) for a, la, lo in db.execute(
            "SELECT asset_id, latitude, longitude FROM assets WHERE latitude IS NOT NULL")}
    out = {}
    for r in library.rows:
        if r["asset_id"] in gps:
            when = datetime.fromisoformat(r["taken_at"].replace("Z", "+00:00"))
            la, lo = gps[r["asset_id"]]
            out[r["asset_id"]] = Asset(id=r["asset_id"], type="IMAGE", file_created_at=when,
                                       file_modified_at=when, updated_at=when,
                                       exif_info=ExifInfo(latitude=la, longitude=lo))
    return out


def scoped(library, config, scope, assets):
    home = home_of(config.trips)
    if scope == "trips" and home:
        trips = detect_trips(sorted(assets.values(), key=lambda a: a.file_created_at), *home,
                             min_distance_km=config.trips.min_distance_km,
                             min_duration_days=config.trips.min_duration_days,
                             max_gap_days=config.trips.max_gap_days, name_locations=False)
        ids = {i for t in trips for i in t.asset_ids}
        return {i for i, r in enumerate(library.rows) if r["asset_id"] in ids}, f"{len(trips)} trips"
    if scope == "home" and home:
        near = {a for a, x in assets.items()
                if near_home_of(home, [(x.exif_info.latitude, x.exif_info.longitude)])}
        return {i for i, r in enumerate(library.rows) if r["asset_id"] in near}, f"within {HOME_RADIUS_KM} km of home"
    return set(range(len(library.rows))), "whole library"


def immich(config):
    return httpx.Client(base_url=config.immich.url, headers={"x-api-key": config.immich.api_key}, timeout=60)


def add_uncaptioned(library, items):
    """Pictures the caption bank never saw (forwarded, not prepared) join as caption-less rows:
    the visual check judges them, and the film captions them on demand."""
    known = {r["asset_id"]: i for i, r in enumerate(library.rows)}
    added = set()
    for a in items:
        if a["id"] in known:
            continue
        library.rows.append({"asset_id": a["id"], "taken_at": a["fileCreatedAt"], "caption": "",
                             "media_kind": a.get("type", "IMAGE").lower(), "city": "", "country": "",
                             "person_refs": [], "uncaptioned": True})
        library.tokens.append(set())
        known[a["id"]] = len(library.rows) - 1
        added.add(known[a["id"]])
    return {known[a["id"]] for a in items}, added


def search_all(config, body, cap=4000):
    items, page = [], 1
    with immich(config) as c:
        while page and len(items) < cap:
            d = c.post("/api/search/metadata", json=body | {"size": 1000, "page": page}).json()
            items += d.get("assets", {}).get("items", [])
            page = d.get("assets", {}).get("nextPage")
            page = int(page) if page else None
    return items


def read_in_photos(config, texts):
    """Immich OCR: letters really in the photo, forwarded pictures included."""
    return [a for t in texts for a in search_all(config, {"ocr": t})]


def event_members(config, library, anchors):
    """Everything Immich holds within an anchor's episode, forwarded batches included."""
    when = sorted(datetime.fromisoformat(library.rows[i]["taken_at"].replace("Z", "+00:00")) for i in anchors)
    windows = []
    for t in when:
        if windows and t - EPISODE <= windows[-1][1]:
            windows[-1][1] = t + EPISODE
        else:
            windows.append([t - EPISODE, t + EPISODE])
    items = []
    for a, b in windows[:200]:
        items += search_all(config, {"takenAfter": a.isoformat(), "takenBefore": b.isoformat()}, cap=500)
    return items


def _unused_read_in_photos(config, texts):
    found = set()
    with httpx.Client(base_url=config.immich.url, headers={"x-api-key": config.immich.api_key},
                      timeout=60) as c:
        for text in texts:
            page = 1
            while page:
                d = c.post("/api/search/metadata", json={"ocr": text, "size": 1000, "page": page}).json()
                found |= {a["id"] for a in d.get("assets", {}).get("items", [])}
                page = d.get("assets", {}).get("nextPage")
                page = int(page) if page else None
    return found


def around(library, anchors):
    """Each anchor's episode: pictures within the product's 90-minute gap of it."""
    when = [datetime.fromisoformat(r["taken_at"].replace("Z", "+00:00")) for r in library.rows]
    times = sorted(when[i] for i in anchors)
    return {i for i, t in enumerate(when) if any(abs(t - a) <= EPISODE for a in times)}


LOOK = '''Look at the photo{ref}. Answer each question with true or false from what is
visible{same}. Return JSON {{"why":short,"answers":[booleans, one per question],"same":{same_values}}}.
Questions: {questions}'''
LOOK_BUDGET = int(os.environ.get("LOOK_BUDGET", 160))


def look_schema(n_questions, with_ref):
    # The free-text reason first: a free field last is where the enforced grammar stalls.
    props = {"why": {"type": "string", "maxLength": 200},
             "answers": {"type": "array", "items": {"type": "boolean"},
                         "minItems": n_questions, "maxItems": n_questions}}
    if with_ref:
        props["same"] = {"type": "string", "enum": ["same", "different", "cannot_tell"]}
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def truthy(value):
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def preview(config, asset_id):
    r = httpx.get(f"{config.immich.url}/api/assets/{asset_id}/thumbnail?size=preview",
                  headers={"x-api-key": config.immich.api_key}, timeout=60)
    r.raise_for_status()
    return "data:image/jpeg;base64," + base64.b64encode(r.content).decode()


def ask_images(llm, text, images, schema=None):
    content = [{"type": "text", "text": text}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
    body = {"model": llm.model, "messages": [{"role": "user", "content": content}],
            "max_tokens": 300, "temperature": 0, **llm.extra_params, **llm.no_thinking_params}
    if schema:
        # Enforced: an answer of the string "false" once counted as a yes (09-27).
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "look", "schema": schema, "strict": True}}
    r = httpx.post(llm.base_url.rstrip("/") + "/chat/completions", json=body, timeout=180,
                   headers=openai_headers(llm), trust_env=False)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"]
    return json.loads(raw[raw.find("{"): raw.rfind("}") + 1])


def look(reader, config, library, plan, candidates, anchors):
    """The one place pictures are shown to a model: this feature only (owner ruling 09-27).

    Questions come from the sentence alone. A reference is a photo the letters vouch for (an
    OCR anchor) or, for one thing followed over time, the earliest photo that passes. Only an
    explicit "different" drops a picture; "cannot tell" stays (a room is not its facade).
    """
    # A question about the picture's subject is about a photograph of it, not a painting or a screen.
    # Letters are OCR's job: a rider seen from behind cannot show them, the reference can.
    texts = [t.lower() for t in plan.get("read_text") or []]
    general = [q.rstrip("?") + " (in a real photograph, not a painting, poster or screen)?"
               for q in plan.get("visual_questions") or [] if not any(t in q.lower() for t in texts)]
    per_item = plan.get("_per_item_questions") or {}
    thing = plan.get("same_thing")
    if not general and not thing and not per_item and not anchors:
        return candidates, []
    cache = ROOT / "looks"
    cache.mkdir(exist_ok=True)
    # The budget is spread across years, anchors first: a date-ordered cut drops every late year.
    years = defaultdict(list)
    for i in sorted(candidates, key=lambda i: library.rows[i]["taken_at"]):
        years[library.rows[i]["taken_at"][:4]].append(i)
    share = max(1, LOOK_BUDGET // max(1, len(years)))
    spread = [i for refs in years.values() for i in refs[:: max(1, len(refs) // share)][:share]]
    ordered = sorted(set(spread) | (set(candidates) & anchors),
                     key=lambda i: (i not in anchors, library.rows[i]["taken_at"]))[:LOOK_BUDGET + len(anchors)]
    reference = None
    subject_words = " / ".join(plan.get("subject") or [])
    for i in [i for i in ordered if i in anchors][:12]:
        # The reference must show the subject: the first OCR hit can be a sticker on a device.
        try:
            probe = ask_images(reader.llm, f'Does this photo show {subject_words or "the subject"} '
                               '(a real photograph, not a screenshot or a screen)? Return JSON.',
                               [preview(config, library.rows[i]["asset_id"])],
                               schema={"type": "object", "additionalProperties": False,
                                       "properties": {"answer": {"type": "boolean"}}, "required": ["answer"]})
        except (httpx.HTTPError, ValueError, KeyError):
            continue
        if truthy(probe.get("answer")):
            reference = library.rows[i]["asset_id"]
            break
    ref_image = preview(config, reference) if reference else None
    kept, log = [], []
    for i in ordered:
        aid = library.rows[i]["asset_id"]
        questions = per_item.get(i) or general
        use_ref = ref_image is not None and aid != reference
        text = LOOK.format(ref=" (the first image is the reference, the second is the photo to judge)" if use_ref else "",
                           same=(f', and whether it shows the same {thing or " / ".join(plan.get("subject") or ["subject"])} '
                                 "as the reference (the same place, people, clothing or object)") if use_ref else "",
                           same_values='"same|different|cannot_tell"' if use_ref else "null",
                           questions=json.dumps(questions))
        key = hashlib.sha256((text + aid + (reference or "")).encode()).hexdigest()[:20]
        path = cache / f"{key}.json"
        if path.exists():
            answer = json.loads(path.read_text())
        else:
            try:
                answer = ask_images(reader.llm, text, ([ref_image] if use_ref else []) + [preview(config, aid)],
                                    schema=look_schema(len(questions), use_ref))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                answer = {"answers": [], "same": None, "why": f"error: {exc}"}
            save(path, answer)
        ok = all(truthy(x) for x in (answer.get("answers") or [False])) if questions else True
        ok = ok and answer.get("same") != "different"
        log.append({"date": library.rows[i]["taken_at"][:10], "caption": library.rows[i]["caption"][:80],
                    "answers": answer.get("answers"), "same": answer.get("same"), "why": answer.get("why", "")[:120],
                    "kept": ok})
        if ok:
            kept.append(i)
            if thing and ref_image is None:
                reference, ref_image = aid, preview(config, aid)
    return kept, log


FIRSTS = '''Below are things that appear for the first time in pictures of {who}, each with
the date, {who}'s age that day, the first caption and a later one. Pick the (at most three)
that are the most memorable real firsts of something new for {who}: an experience, a place, a
food, an activity, a skill, an encounter. None of them when none qualifies. Clothes, colours,
furniture, camera angles and words that only describe the scene are not firsts. Return JSON.'''


def known_people():
    import yaml

    data = yaml.safe_load((Path.home() / ".immich-memories/people.yaml").read_text()) or {}
    people = data.get("people") or []
    people = people.values() if isinstance(people, dict) else people
    return {v.get("name"): v for v in people if isinstance(v, dict) and v.get("name")}


def person_rows(library, person):
    refs = {"P" + hashlib.sha256(str(i).encode()).hexdigest()[:10] for i in person.get("ids") or []}
    return {i for i, r in enumerate(library.rows) if refs & set(r.get("person_refs") or [])}


def firsts(reader, library, key, name, person, rows):
    """First appearance of every caption word in a person's pictures, judged by E4B."""
    from datetime import date

    born = person.get("birth_date")
    born = date.fromisoformat(str(born)) if born else None
    ordered = sorted(rows, key=lambda i: library.rows[i]["taken_at"])
    if not ordered:
        return [], []
    start = date.fromisoformat(library.rows[ordered[0]]["taken_at"][:10])
    seen, days_of = {}, defaultdict(set)
    for i in ordered:
        d = date.fromisoformat(library.rows[i]["taken_at"][:10])
        for t in library.tokens[i]:
            days_of[t].add(d)
            seen.setdefault(t, i)
    n = len(library.rows)
    cands = []
    from nltk.corpus import wordnet as wn

    for t, i in seen.items():
        # Things and actions only: an adjective or a function word is not a first.
        # Things only (a place, a food, an animal, an object, an event), and never a verb form.
        if t in FILLER_WORDS or not wn.synsets(t, pos=wn.NOUN) or wn.synsets(t, pos=wn.ADJ) or t.endswith(("ing", "ed", "es")) and wn.synsets(t, pos=wn.VERB):
            continue
        first = date.fromisoformat(library.rows[i]["taken_at"][:10])
        later = sorted(days_of[t])
        # New (not there from the start), and it came back: a new thing, not a one-off word.
        if (first - start).days < 21 or len(later) < 3:
            continue
        specific = math.log(n / max(1, len(library.posts.get(t, ()))))
        cands.append((specific, t, i, later))
    cands = sorted(cands, reverse=True)[:90]
    offered = []
    for j, (_, t, i, later) in enumerate(sorted(cands, key=lambda c: library.rows[c[2]]["taken_at"])):
        first = date.fromisoformat(library.rows[i]["taken_at"][:10])
        age = f"{(first - born).days // 30} months" if born else "unknown"
        again = next((k for k in rows if t in library.tokens[k] and library.rows[k]["taken_at"][:10] > str(later[1])), i)
        offered.append({"id": j, "word": t, "date": str(first), "age": age,
                        "first_caption": library.rows[i]["caption"][:120],
                        "later_caption": library.rows[again]["caption"][:120], "_ref": i})
    # Compared, not yes/no: a 4B judge says yes to nearly everything it sees alone.
    chosen = []
    for start_ix in range(0, len(offered), 10):
        part = offered[start_ix:start_ix + 10]
        schema = _schema(picked={"type": "array", "items": {"type": "integer", "enum": [o["id"] for o in part]},
                                 "maxItems": 3})
        answer = reader.ask("firsts_pick", f"{key}:{start_ix}", FIRSTS.format(who=name.split()[0]),
                            [{k: v for k, v in o.items() if k != "_ref"} for o in part], lambda a: None, 300,
                            schema=schema)
        by_id = {o["id"]: o for o in part}
        chosen += [by_id[i] | {"label": "first " + by_id[i]["word"]} for i in (answer or {"picked": []})["picked"]]
    # Every batch fills its three slots, junk batches too: one final comparison keeps the best.
    if len(chosen) > 12:
        ids = {j: c for j, c in enumerate(chosen)}
        schema = _schema(picked={"type": "array", "items": {"type": "integer", "enum": list(ids)}, "maxItems": 12})
        final = reader.ask("firsts_final", f"{key}:final", FIRSTS.replace("(at most three)", "(at most twelve)").format(
                           who=name.split()[0]), [{"id": j, "word": c["word"], "date": c["date"], "age": c["age"],
                           "first_caption": c["first_caption"]} for j, c in ids.items()], lambda a: None, 400,
                           schema=schema)
        chosen = sorted((ids[j] for j in (final or {"picked": list(ids)})["picked"]), key=lambda c: c["date"])
    return chosen, offered


def main():
    brief = sys.argv[1]
    key = "translate:" + hashlib.sha256(brief.encode()).hexdigest()[:16]
    library, reader = load_library(), Reader()
    config = Config.from_yaml(Path.home() / ".immich-memories/config.yaml")
    since, until = years_of(brief)

    def valid(a):
        assert a["scope"] in {"any", "home", "trips"}
        assert all(isinstance(a[k], list) for k in ("subject", "read_text", "exclusions", "unverifiable"))

    people = known_people()
    plan = ask_plan(reader, key, brief, {"caption_vocabulary": vocabulary(300)}, library, people)
    if plan is None:
        raise SystemExit("E4B returned no valid plan")
    plan |= {"since": since, "until": until}
    for field, default in (("title", brief[:60]), ("unmapped", []), ("people", []), ("firsts", False),
                           ("same_thing", None), ("visual_questions", []), ("exclusions", []),
                           ("unverifiable", [])):
        plan.setdefault(field, default)
    # Qualifiers are joined to the subject by code, not left to the model to remember.
    if plan.get("qualifiers") and plan["subject"]:
        plan["subject"] = [f"{q} {s}" for q in plan["qualifiers"] for s in plan["subject"]
                           if q.lower() not in s.lower()] + [s for s in plan["subject"]
                           if any(q.lower() in s.lower() for q in plan["qualifiers"])]
    # A scope narrows only when the sentence states it, like dates: "club rides" is not a trip.
    stated = {"trips": r"\b(holiday|holidays|vacation|trip|trips|travel|travels|abroad|journey)\b",
              "home": r"\b(home|house|flat|apartment|our place|garden)\b"}
    if plan["scope"] in stated and not re.search(stated[plan["scope"]], brief, re.I):
        plan["scope_dropped"], plan["scope"] = plan["scope"], "any"
    bank = os.environ.get("BANK") or config.editorial.resolve_annotation_database(config.cache.cache_path)
    assets = bank_assets(library, bank)
    in_window = {i for i, r in enumerate(library.rows)
                 if (since or 1) <= int(r["taken_at"][:4]) <= (until or 9999)}
    scope, scope_note = scoped(library, config, plan["scope"], assets)
    pool_scope = in_window & scope

    named = [people[p] | {"name": p} for p in plan.get("people") or [] if p in people]
    if named:
        # Who is in a picture is Immich's face data, never a caption word.
        pool_scope &= set().union(*(person_rows(library, p) for p in named))
    if plan.get("firsts") and named:
        chosen, offered = firsts(reader, library, key, named[0]["name"], named[0], pool_scope)
        plan["subject"], plan["read_text"] = [], []
        pool_scope = {c["_ref"] for c in chosen}
        plan["firsts_found"] = [f'{c["date"]} ({c["age"]}): {c["label"]}' for c in chosen]
        plan["firsts_offered"] = len(offered)
        # A first is checked for itself: does the photo show that thing, not "is it a first".
        plan["visual_questions"], plan["same_thing"] = [], None
        plan["_per_item_questions"] = {c["_ref"]: [f'Does this photo show {named[0]["name"].split()[0]} with or at: {c["label"]}?']
                                       for c in chosen}
    subject = set()
    if plan["subject"]:
        own, companions = companion_terms(reader, library, brief, key)
        phrases = plan["subject"] + own + [f"{a} {b}" for k, a in enumerate(companions) for b in companions[k + 1:]]
        plan["subject_phrases"] = phrases
        subject = set(retrieve_plan(library, {"queries": phrases, "places": [], "since": since, "until": until}))
    anchors, uncaptioned = set(), set()
    if plan["read_text"]:
        anchors, new = add_uncaptioned(library, read_in_photos(config, plan["read_text"]))
        anchors = {i for i in anchors if (since or 1) <= int(library.rows[i]["taken_at"][:4]) <= (until or 9999)}
        members, more = add_uncaptioned(library, event_members(config, library, anchors))
        uncaptioned = {i for i in (new | more) if i in members | anchors}
        pool_scope |= anchors | members  # the event decides here, not the trip/home scope
        # A letter read in one photo vouches for its event: captioned pictures of the subject,
        # and caption-less ones (forwarded) that the visual check will judge.
        subject = (subject & members) | anchors | uncaptioned if subject else members | anchors
    pool = (subject if (plan["subject"] or plan["read_text"]) else pool_scope) & pool_scope

    by_year = defaultdict(list)
    for i in sorted(pool, key=lambda i: library.rows[i]["taken_at"]):
        by_year[library.rows[i]["taken_at"][:4]].append(i)
    offered = [i for refs in by_year.values() for i in refs[:: max(1, len(refs) // PER_YEAR)][:PER_YEAR]]
    offered = [i for i in offered if not library.rows[i].get("uncaptioned")]
    decisions = choose_sources(reader, library, key, brief,
                               sorted(set(offered) | {i for i in anchors & pool if not library.rows[i].get("uncaptioned")}))
    kept = sorted((d["ref"] for d in decisions if d["decision"] == "match"),
                  key=lambda i: library.rows[i]["taken_at"])
    unsure = [d["ref"] for d in decisions if d["decision"] == "unknown"]
    looked = []
    if not os.environ.get("NO_LOOK"):
        kept, looked = look(reader, config, library, plan, set(kept) | set(unsure) | (uncaptioned & pool), anchors)
        kept.sort(key=lambda i: library.rows[i]["taken_at"])
    timeline = [f'{library.rows[i]["taken_at"][:10]}: {library.rows[i]["caption"][:110]}'
                for i in kept[:: max(1, len(kept) // 24)]]
    thesis = reader.ask("translate_thesis", key, THESIS, {"owner_request": brief, "timeline": timeline},
                        lambda a: isinstance(a["thesis"], str), 400) if kept else None
    plan.pop("_per_item_questions", None)
    record = {"brief": brief, "plan": plan, "scope": scope_note,
              "counts": {"window": len(in_window), "scope": len(pool_scope), "subject_matches": len(subject),
                         "ocr_anchors": len(anchors), "uncaptioned": len(uncaptioned & pool), "pool": len(pool), "judged": len(decisions),
                         "looked": len(looked), "kept": len(kept)},
              "kept_by_year": dict(sorted(Counter(library.rows[i]["taken_at"][:4] for i in kept).items())),
              "thesis": (thesis or {}).get("thesis"),
              "sample": [f'{library.rows[i]["taken_at"][:10]} {library.rows[i]["caption"][:90]}'
                         for i in kept[:: max(1, len(kept) // 10)]]}
    save(ROOT / "translations" / f"{key[10:]}.json", record | {"looked": looked,
         "asset_ids": [library.rows[i]["asset_id"] for i in kept]})
    print(json.dumps(record, ensure_ascii=False, indent=1))
    if os.environ.get("FILM_DRY") or len(kept) < 5:
        return
    intent = ROOT / "translations" / f"{key[10:]}.intent.json"
    intent.write_text(json.dumps({"asset_ids": [library.rows[i]["asset_id"] for i in kept],
                                  "thesis": record["thesis"] or brief}))
    first, last = library.rows[kept[0]]["taken_at"][:10], library.rows[kept[-1]]["taken_at"][:10]
    # Owner ruling: free-text films keep forwarded pictures (a club's photos arrive by chat).
    subprocess.run(["/private/tmp/imm-threads/.venv/bin/immich-memories", "generate", "--start", first,
                    "--end", last, "--title", plan.get("title") or brief[:60], "--accept-any-provenance"],
                   env=os.environ | {"IMMICH_MEMORIES_INTENT": str(intent)}, check=False)


if __name__ == "__main__":
    main()
