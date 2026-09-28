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
from cascade import (AGREE, GRAMMAR_SAMPLE, SMOL_SAMPLE, ask_contradictions, banked_heads, grammar_says_subject,
                     ladder, smol_yes)
from spec import AT_HOME_KM, at_home_rows, build_spec, build_subject, homes, show
from query import companion_terms, retrieve_plan, vocabulary
from workflow import choose_sources

def _list(desc, most=6):
    return {"type": "array", "items": {"type": "string"}, "maxItems": most, "description": desc}


def _schema(**props):
    # Every key required and every list capped: oMLX's enforced grammar stalls when the model
    # wants to stop before a required key, and optional keys get skipped (measured 09-27).
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


# No minItems: the enforced grammar stalls when the model wants to stop early (measured again 09-27).
SUBJECT_SCHEMA = _schema(subject=_list("what must be visible, and the other words captions use for it", 8))
SUBJECT = '''What must be visible in the photos this request asks for? Use plain words a photo
caption would use (caption_vocabulary), keeping any colour, size or kind the request states
("black cat", not "cat"), then add the other words captions use for the same thing: its kinds,
common names or makes. Return JSON.'''
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


PEOPLE = '''Which of these people is the owner's request about? Each has a name and, when
known, a role relative to the owner. Pick only people the request names or clearly refers to;
none when it is about no one in particular. Return JSON.'''


def ask_people(reader, key, brief, people):
    """Gemma links names and roles ("my son") to the people file; the enum forbids inventing one."""
    listed = {n: str(((p.get("confirmed") or {}).get("role") or (p.get("inferred") or {}).get("role") or ""))
              for n, p in people.items() if (p.get("inferred") or {}).get("tier") in {"inner", "recurring"}
              or (p.get("confirmed") or {}).get("role")}
    if not listed:
        return []
    schema = _schema(people={"type": "array", "items": {"type": "string", "enum": sorted(listed)}, "maxItems": 4})
    import yaml

    owner = (yaml.safe_load((Path.home() / ".immich-memories/people.yaml").read_text()) or {}).get("owner")
    owner_name = owner.get("name") if isinstance(owner, dict) else owner
    if owner_name in listed:
        # "I", "me", "my" are the owner: say so, as the other roles say who someone is.
        listed[owner_name] = "the owner themself (I, me, my)"
    answer = reader.ask("plan_people", key, PEOPLE, {"owner_request": brief,
                        "the_owner_who_says_my_and_our": (owner.get("name") if isinstance(owner, dict) else owner) or None,
                        "people": [{"name": n, "role_relative_to_owner": r} for n, r in sorted(listed.items())]},
                        lambda a: None, 200, schema=schema)
    return (answer or {"people": []})["people"]


FILTERS = '''Turn the owner's request into filters over their photo library. Use the facts given
(people with their roles and birth dates, today's date, years found in the request) to decide:
the date range the photos were taken in (YYYY-MM-DD, or null for no bound), and whether the listed
people's faces must be recognised in every photo. A request about one moment or event gets the
short range that moment covers; only a request that runs on ("since", "along the years") leaves
the end open. Return JSON.'''


def ask_filters(reader, key, brief, named, years):
    """Filters, not operators: Gemma derives a date range and a face requirement from real facts."""
    date = {"type": ["string", "null"], "pattern": "^[12][0-9]{3}-[01][0-9]-[0-3][0-9]$"}
    schema = _schema(date_from=date, date_to=date, faces_required={"type": "boolean"})
    answer = reader.ask("plan_filters", key, FILTERS, {
        "owner_request": brief, "today": datetime.now(UTC).date().isoformat(), "years_in_request": years,
        "people": [{"name": p["name"], "role": str((p.get("confirmed") or {}).get("role") or ""),
                    "born": str(p.get("birth_date") or "unknown")} for p in named]},
        lambda a: None, 200, schema=schema)
    return answer or {"date_from": None, "date_to": None, "faces_required": bool(named)}


PHOTO_QUESTION = '''The owner asked for a photo film. Write the one yes/no question to ask of a
single photo to decide whether it belongs: about what is visible in that one photo, not about
time spans, dates or who someone is (a photo cannot show "across the years" or a name). Ask whether
it is the main subject of the photo, not something in the background. Keep an action the request
names only when one photo can show it (someone feeding, riding); do not require it otherwise.
Return JSON.'''


def ask_photo_question(reader, key, brief):
    """The refinement question is Gemma's: what one photo must visibly show for this request."""
    answer = reader.ask("photo_question", key, PHOTO_QUESTION, {"owner_request": brief}, lambda a: None, 150,
                        schema=_schema(question={"type": "string", "maxLength": 160}))
    return (answer or {}).get("question") or f'Does this photo show what "{brief.strip()}" asks for?'


ENGLISH = '''Give the owner's request in English. If it is already English, return it unchanged.
Translate every ordinary word (animals, objects, activities, relatives); keep only proper names of
people, places and organisations as written. Return JSON.'''


def to_english(reader, key, text):
    answer = reader.ask("to_english", key, ENGLISH, {"owner_request": text}, lambda a: None, 200,
                        schema=_schema(english={"type": "string", "maxLength": 400}))
    return ((answer or {}).get("english") or text).strip()


def ask_plan(reader, key, brief, context, library, people):
    plan = parse_structure(brief, people, library)
    plan["people"] = ask_people(reader, key, brief, people)
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
    # Refine against the ask, not the search words: the pool may come from "woman, baby"; the
    # film is about what the owner wrote.
    plan["visual_questions"] = [ask_photo_question(reader, key, brief)]
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

IMMICH_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
EPISODE = timedelta(minutes=90)  # the product's episode gap (selection_source_groups)
JUDGE_BUDGET = 220               # caption checks per request, spread over the pool's time scale


def subject_kinds(library, subject):
    """The kinds of each subject noun that captions actually use (WordNet hyponyms): "car" also
    finds "convertible", "sedan", "suv". Wrong senses are left to the caption and photo checks."""
    from nltk.corpus import wordnet as wn

    found = []
    for phrase in subject:
        head = phrase.split()[-1]
        for synset in wn.synsets(head, pos=wn.NOUN)[:1]:
            for kind in synset.closure(lambda s: s.hyponyms()):
                for lemma in kind.lemmas():
                    word = lemma.name().lower()
                    if "_" not in word and word in library.posts and word not in found and word != head:
                        found.append(word)
    # WordNet's closure order follows set hashing: sort, most-used first, so a run repeats itself.
    return sorted(found, key=lambda w: (-len(library.posts[w]), w))[:40]


def spread_budget(library, refs, budget, score=None):
    """An even sample over the pool's own time scale: days for a birth, months for a season,
    years for "along the years"."""
    refs = sorted(refs, key=lambda i: library.rows[i]["taken_at"])
    if not refs:
        return []
    first, last = library.rows[refs[0]]["taken_at"][:10], library.rows[refs[-1]]["taken_at"][:10]
    span = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days
    width = 4 if span > 730 else 7 if span > 62 else 10  # year, month or day buckets
    buckets = defaultdict(list)
    for i in refs:
        buckets[library.rows[i]["taken_at"][:width]].append(i)
    share = max(1, budget // len(buckets))
    if score:
        # Best matches first, then variety: among equally relevant captions, the one describing
        # something the picks do not yet (a red Mustang) beats the tenth "busy street with cars".
        out = []
        for b in buckets.values():
            left = sorted(b, key=lambda i: -score.get(i, 0))
            seen, picked = set(), []
            while left and len(picked) < share:
                # Every caption of the period competes: a cap on the date-ordered list cut December.
                best = max(left, key=lambda i: (score.get(i, 0), len(library.tokens[i] - seen)))
                picked.append(best)
                seen |= library.tokens[best]
                left.remove(best)
            out += picked
        return out
    return [i for b in buckets.values() for i in b[:: max(1, len(b) // share)][:share]]


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
CALIBRATION, TRUST_TEXT = 24, 0.8  # sample of text yeses checked by photo; agreement needed to trust text


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


def look(reader, config, library, plan, candidates, anchors, score=None):
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
    # Spread over the pool's own time scale, anchors first: a date-ordered cut drops every late period.
    budget = min(320, max(LOOK_BUDGET, len(candidates) // 3))
    plan.setdefault("budgets", {})["look"] = budget
    spread = spread_budget(library, candidates, budget, score)
    ordered = sorted(set(spread) | (set(candidates) & anchors),
                     key=lambda i: (i not in anchors, library.rows[i]["taken_at"]))[:budget + len(anchors)]
    # No "same one as the reference" check: on the owner's labels it dropped 36 good cat photos and
    # good house photos ("clearly shows a black cat") and never helped once (09-27).
    reference = None
    ref_image = preview(config, reference) if reference else None
    kept, log = [], []
    # SmolVLM and E4B both answer until SMOL_SAMPLE pairs exist for this request; SmolVLM
    # then answers alone when they agreed on at least AGREE of them (cascade.py).
    state = plan.setdefault("cascade", {"smol_trusted": None, "pairs": 0, "agreed": 0, "smol": 0, "e4b": 0})
    for i in ordered:
        aid = library.rows[i]["asset_id"]
        questions = per_item.get(i) or general
        if state and state["smol_trusted"] and questions:
            small = [smol_yes(config, q, aid, preview) for q in questions]
            if None not in small:
                ok = all(small)
                state["smol"] += 1
                log.append({"date": library.rows[i]["taken_at"][:10], "caption": library.rows[i]["caption"][:80],
                            "answers": small, "same": None, "why": "smolvlm", "kept": ok})
                if ok:
                    kept.append(i)
                continue
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
        if state is not None:
            state["e4b"] += 1
            if state["smol_trusted"] is None and questions:
                small = [smol_yes(config, q, aid, preview) for q in questions]
                if None not in small:
                    state["pairs"] += 1
                    state["agreed"] += all(small) == ok
                if state["pairs"] >= SMOL_SAMPLE:
                    state["smol_trusted"] = state["agreed"] / state["pairs"] >= AGREE
        log.append({"date": library.rows[i]["taken_at"][:10], "caption": library.rows[i]["caption"][:80],
                    "answers": answer.get("answers"), "same": answer.get("same"), "why": answer.get("why", "")[:120],
                    "kept": ok})
        if ok:
            kept.append(i)
            if False:  # reference check removed (see above)
                reference, ref_image = aid, preview(config, aid)
    return kept, log


FIRSTS = '''Below are words that appear for the first time in {who}'s own photos, each with the date,
{who}'s age that day and that first caption. Which of them are the most meaningful firsts for {who}: the
first time {who} met, did, saw, ate or went to something? Pick at most three; none when none is.
Return JSON.'''
FIRSTS_KEPT = 60  # compared again in groups of ten until about this many remain


def known_people():
    import yaml

    data = yaml.safe_load((Path.home() / ".immich-memories/people.yaml").read_text()) or {}
    people = data.get("people") or []
    people = people.values() if isinstance(people, dict) else people
    return {v.get("name"): v for v in people if isinstance(v, dict) and v.get("name")}


def person_rows(library, person):
    refs = {"P" + hashlib.sha256(str(i).encode()).hexdigest()[:10] for i in person.get("ids") or []}
    return {i for i, r in enumerate(library.rows) if refs & set(r.get("person_refs") or [])}


def present_rows(library, person):
    """A person is present in a photo when their face is recognised anywhere in its episode:
    a baby feeding against a chest or a child seen from behind has no recognised face."""
    import bisect

    face = person_rows(library, person)
    when = [datetime.fromisoformat(r["taken_at"].replace("Z", "+00:00")) for r in library.rows]
    times = sorted(when[i] for i in face)
    out = set(face)
    for i, t in enumerate(when):
        k = bisect.bisect_left(times, t - EPISODE)
        if k < len(times) and times[k] <= t + EPISODE:
            out.add(i)
    return out


def firsts(reader, library, key, name, person, rows):
    """The first occurrence of every noun in the person's own photos (their face is recognised in
    it), in date order; E4B keeps the meaningful ones, ten at a time, as many as it finds."""
    from datetime import date

    from nltk.corpus import wordnet as wn

    born = person.get("birth_date")
    born = date.fromisoformat(str(born)) if born else None
    own = sorted(set(rows) & person_rows(library, person), key=lambda i: library.rows[i]["taken_at"])
    first = {}
    for i in own:
        for t in sorted(library.tokens[i]):
            # Grammar, not meaning: a first is a thing or an event, so nouns only.
            if t not in first and t not in FILLER_WORDS and wn.synsets(t, pos=wn.NOUN):
                first[t] = i
    offered = []
    for j, (t, i) in enumerate(sorted(first.items(), key=lambda kv: (library.rows[kv[1]]["taken_at"], kv[0]))):
        day = date.fromisoformat(library.rows[i]["taken_at"][:10])
        age = f"{(day - born).days // 30} months" if born else "unknown"
        offered.append({"id": j, "word": t, "date": str(day), "age": age,
                        "first_caption": library.rows[i]["caption"][:120], "_ref": i})
    # Compared, not yes/no: asked to keep every meaningful one, E4B kept 774 of 1835 (09-28).
    # Each round keeps at most three of every ten, in date order, until about FIRSTS_KEPT remain.
    chosen, rnd = offered, 0
    while len(chosen) > FIRSTS_KEPT:
        kept = []
        for start_ix in range(0, len(chosen), 10):
            part = chosen[start_ix:start_ix + 10]
            schema = _schema(picked={"type": "array", "items": {"type": "integer", "enum": [o["id"] for o in part]},
                                     "maxItems": 3})
            answer = reader.ask("firsts_compare", f"{key}:r{rnd}:{start_ix}", FIRSTS.format(who=name.split()[0]),
                                [{k: v for k, v in o.items() if k not in {"_ref", "label"}} for o in part],
                                lambda a: None, 200, schema=schema)
            by_id = {o["id"]: o for o in part}
            kept += [by_id[i] for i in (answer or {"picked": []})["picked"] if i in by_id]
        if len(kept) >= len(chosen):
            break
        chosen, rnd = sorted(kept, key=lambda o: (o["date"], o["word"])), rnd + 1
    return [c | {"label": "first " + c["word"]} for c in chosen], offered


COMPACT = '''For each numbered photo caption, answer whether that photo belongs in the film the owner
asked for, as what_belongs describes it: "yes" only when the caption makes it the main subject of
the photo, "no" when it is absent, only in the background, or what_belongs rules it out, "unsure"
when the caption cannot tell.
Captions never know names or whose something is. Return JSON with one answer per caption, in order.'''
COMPACT_BATCH = 24


def choose_compact(reader, library, key, brief, refs, meaning=None, core=None, not_this=(), stats=None):
    """The cheap text check: one short enforced verdict per caption, no reasons (reasons were
    ~90% of the time: 1.6 s per caption). Grammar's "belongs" stands for the captions it
    names when Gemma agrees on a sample of them (cascade.py)."""
    refs = [i for i in refs if library.rows[i]["caption"]]
    if core:
        named = [i for i in refs if grammar_says_subject(library.rows[i]["caption"], core, not_this)]
        if named:
            import random as _random

            sample = sorted(_random.Random(7).sample(named, min(GRAMMAR_SAMPLE, len(named))))
            checked = _gemma_compact(reader, library, f"{key}:grammar", brief, sample, meaning)
            agree = sum(d["decision"] == "match" for d in checked) / len(checked)
            if stats is not None:
                stats.update({"grammar_named": len(named), "grammar_agreement": round(agree, 2),
                              "grammar_trusted": agree >= AGREE})
            if agree >= AGREE:
                taken = set(named)
                return checked + [{"ref": i, "decision": "match", "by": "grammar"} for i in named if i not in set(sample)] \
                    + _gemma_compact(reader, library, key, brief, [i for i in refs if i not in taken], meaning)
    return _gemma_compact(reader, library, key, brief, refs, meaning)


def _gemma_compact(reader, library, key, brief, refs, meaning):
    # A burst's identical captions get one verdict.
    first = {}
    for i in refs:
        first.setdefault(library.rows[i]["caption"], i)
    unique = _gemma_compact_all(reader, library, key, brief, list(first.values()), meaning)
    verdict = {library.rows[d["ref"]]["caption"]: d["decision"] for d in unique}
    return [{"ref": i, "decision": verdict[library.rows[i]["caption"]]} for i in refs]


def _gemma_compact_all(reader, library, key, brief, refs, meaning):
    decisions = []
    for start in range(0, len(refs), COMPACT_BATCH):
        part = refs[start:start + COMPACT_BATCH]
        schema = _schema(answers={"type": "array", "items": {"type": "string", "enum": ["yes", "no", "unsure"]},
                                  "minItems": len(part), "maxItems": len(part)})
        answer = reader.ask("compact_check", f"{key}:{start}", COMPACT,
                            {"owner_request": brief, "what_belongs": meaning or brief,
                             "captions": [f"{n + 1}. {library.rows[i]['caption'][:140]}" for n, i in enumerate(part)]},
                            lambda a: None, 20 + 6 * len(part), schema=schema)
        verdicts = (answer or {}).get("answers") or ["unsure"] * len(part)
        decisions += [{"ref": i, "decision": {"yes": "match", "no": "reject"}.get(v, "unknown")}
                      for i, v in zip(part, verdicts)]
    return decisions


def save_stages(key, original, spec, library, stages, note=None):
    """What each stage holds, by asset id, for measuring stage by stage (stages_report.py)."""
    save(ROOT / "translations" / f"{key[10:]}.stages.json",
         {"brief": original, "spec": spec, "note": note,
          "stages": {name: sorted(library.rows[i]["asset_id"] for i in refs) for name, refs in stages.items()}})


def main():
    original = sys.argv[1]
    key = "translate:" + hashlib.sha256(original.encode()).hexdigest()[:16]
    library, reader = load_library(), Reader()
    # Captions are English: every later step reads the English request; the original is kept.
    brief = to_english(reader, key, original)
    config = Config.from_yaml(Path.home() / ".immich-memories/config.yaml")
    since, until = years_of(brief)

    people = known_people()
    bank = os.environ.get("BANK") or config.editorial.resolve_annotation_database(config.cache.cache_path)
    assets = bank_assets(library, bank)
    lived = homes(library, assets)
    named = [people[p] | {"name": p} for p in ask_people(reader, key, brief, people) if p in people]
    # The translation, printed before anything runs on it (spec.py): every field is one grounded answer.
    spec = build_spec(reader, key, brief, library, named, lived, [y for y in (since, until) if y])
    plan = {"people": spec["people"], "read_text": spec["text_in_photo"],
            "firsts": spec["shape"] == "first times", "scope": spec["where"]["kind"], "title": brief[:60],
            "same_thing": None, "since": since, "until": until, "exclusions": [], "unverifiable": [],
            "unmapped": []}
    # Test-fixture pictures ("home-breakfast-01") sit in the shared annotation store: only Immich
    # assets can be a film's material (one aborted an album, 09-28).
    in_window = {i for i, r in enumerate(library.rows)
                 if (since or 1) <= int(r["taken_at"][:4]) <= (until or 9999) and IMMICH_ID.match(r["asset_id"])}
    kind = spec["where"]["kind"]
    if kind == "near_home":
        scope = at_home_rows(library, assets, lived, radius=HOME_RADIUS_KM)
        scope_note = f"{len(scope)} pictures within {HOME_RADIUS_KM:.0f} km of the home of the time"
    elif kind in {"home", "home_at_time"}:
        scope = at_home_rows(library, assets, lived, spec["where"]["home"] if kind == "home" else None)
        scope_note = f"{len(scope)} pictures within {AT_HOME_KM * 1000:.0f} m of " + (
            f"the {spec['where']['home']} home" if kind == "home" else "the home of the time")
    else:
        scope, scope_note = scoped(library, config, kind, assets)
    pool_scope = in_window & scope

    named = [people[p] | {"name": p} for p in plan.get("people") or [] if p in people]
    if named:
        # "my son" is a person: faces and presence per episode decide identity. A visual
        # "same as the reference?" is for things (a car, a house, a kit), never people: it
        # dropped 42 of 46 birth photos as "different" from an operating-room reference.
        plan["same_thing"] = None
    filters = {"date_from": spec["when"]["from"], "date_to": spec["when"]["to"],
               "faces_required": spec["people_must_appear"]}
    plan["filters"] = filters
    lo, hi = filters.get("date_from") or "0000", filters.get("date_to") or "9999"
    pool_scope &= {i for i, r in enumerate(library.rows) if lo <= r["taken_at"][:10] <= hi + "z"}
    if named and filters.get("faces_required"):
        # Who is in a picture is Immich's face data, never a caption word, read per episode.
        pool_scope &= set().union(*(present_rows(library, p) for p in named))
    # What the photos show is chosen from candidates the filtered pictures themselves offer.
    spec = build_subject(reader, key, brief, library, spec, pool_scope)
    print(show(spec), file=sys.stderr)
    if os.environ.get("SPEC_ONLY"):
        if spec["shape"] == "first times" and named:
            chosen, offered = firsts(reader, library, key, named[0]["name"], named[0], pool_scope)
            print(f"  firsts        {len(chosen)} of {len(offered)} first words kept: "
                  + ", ".join(f'{c["word"]} ({c["age"]})' for c in chosen), file=sys.stderr)
        print(json.dumps({"brief": original, "spec": spec, "structural": len(pool_scope)}, ensure_ascii=False))
        return
    plan |= {"subject": spec["caption_words"], "visual_questions": [spec["question"]], "meaning": spec["meaning"]}
    if plan.get("firsts") and named:
        chosen, offered = firsts(reader, library, key, named[0]["name"], named[0], pool_scope)
        plan["subject"], plan["read_text"] = [], []
        pool_scope = {c["_ref"] for c in chosen}
        plan["firsts_found"] = [f'{c["date"]} ({c["age"]}): {c["label"]}' for c in chosen]
        plan["firsts_offered"] = len(offered)
        # A first is checked for itself: does the photo show that thing, not "is it a first".
        plan["visual_questions"], plan["same_thing"] = [], None
        # Ask what can be seen ("a carrot"), not who or whether it was a first.
        # A first is someone's: the person with the thing, in a real photograph. Presence per
        # episode lets a screenshot or a stranger share the person's event, so ask for both.
        # Two short questions, both required: one compound question made the small model check
        # only its first half (09-27).
        plan["_per_item_questions"] = {c["_ref"]: [
            "Is this a real photograph (not a screenshot, document or artwork)?",
            f'Does it show a person with {c["word"]}?'] for c in chosen}
    subject = set()
    if plan["subject"]:
        own, companions = companion_terms(reader, library, brief, key)
        first_names = {n.split()[0].lower() for n in people}
        own = [w for w in own if w not in FILLER_WORDS and w not in first_names]
        plan["_own"], plan["_companions"] = own, companions
        pairs = [f"{a} {b}" for k, a in enumerate(companions) for b in companions[k + 1:]]
        # Reverted 09-27: letting the request's rarest words define the subject was tuned to one
        # control and broke the rest (landscapes 131 -> 21, cat -> 0). Gemma's subject leads.
        kinds = subject_kinds(library, plan["subject"])
        plan["subject_kinds"] = kinds
        phrases = plan["subject"] + own + pairs + kinds
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

    # Relevance to the ask: its own specific words weigh most, then their companions, then the subject.
    own_set, comp_set = set(plan.get("_own") or []), set(plan.get("_companions") or [])
    # The kinds found the pool, so they count toward relevance too ("convertible" is a car).
    subj = [set(p.split()) for p in (plan.get("subject") or []) + (plan.get("subject_kinds") or [])]
    # Lexicographic: one hit on the request's own specific word outranks any number of generic
    # hits ("mother", "woman", "baby" tied with "breastfeeding" at 3 and buried it, 09-27).
    score = {i: 10000 * len(own_set & library.tokens[i]) + 100 * len(comp_set & library.tokens[i])
                + sum(1 for p in subj if p <= library.tokens[i]) for i in pool}
    # The cascade: a cheap text verdict on (nearly) every caption, the photo only where text
    # cannot decide. Text "yes" is provisional: the regular flow's thesis-fit vote judges again.
    # The owner's flow (09-27): prompt -> filters -> pool -> thesis -> the regular engine. The
    # engine's thesis-fit vote and story selection do the choosing; no second selector here.
    stages = {"scope": pool_scope, "pool": pool}
    # Run control for prototyping stage by stage (like FILM_DRY): stop after a stage and measure it.
    if os.environ.get("STOP_AFTER") == "pool":
        save_stages(key, original, spec, library, stages)
        print(json.dumps({"brief": original, "stages": {k: len(v) for k, v in stages.items()}}))
        return
    decisions, unsure, looked, kept = [], [], [], sorted(pool, key=lambda i: library.rows[i]["taken_at"])
    if not os.environ.get("SIMPLE"):
        text_budget = int(os.environ.get("TEXT_BUDGET", 3000))
        # Free first: what preparation already recorded (a film is made of photographs).
        heads = banked_heads(bank, [library.rows[i]["asset_id"] for i in pool])
        pool = {i for i in pool if heads.get(library.rows[i]["asset_id"], {}).get("doc_docling", "photograph")
                == "photograph"}
        offered = spread_budget(library, pool, text_budget, score)
        offered = [i for i in offered if not library.rows[i].get("uncaptioned")]
        if plan.get("firsts") and plan.get("_per_item_questions"):
            # Being a first was decided by comparison over dates; a caption cannot show first-ness,
            # so each first goes straight to its own photo question.
            decisions = [{"ref": i, "decision": "unknown"} for i in sorted(pool)]
        else:
            decisions = choose_compact(reader, library, key, brief, meaning=plan.get("meaning"),
                                       core=spec.get("core"), not_this=spec.get("not_this") or (),
                                       stats=plan.setdefault("cascade_captions", {}), refs=
                                       sorted(set(offered) | {i for i in anchors & pool if not library.rows[i].get("uncaptioned")}))
        plan["budgets"] = {"text": len(decisions)}
        kept = sorted((d["ref"] for d in decisions if d["decision"] == "match"),
                      key=lambda i: library.rows[i]["taken_at"])
        unsure = [d["ref"] for d in decisions if d["decision"] == "unknown"]
        stages |= {"caption_yes": set(kept), "caption_unsure": set(unsure),
                   "caption_read": {d["ref"] for d in decisions}}
        if os.environ.get("STOP_AFTER") == "captions":
            save_stages(key, original, spec, library, stages, plan.get("cascade_captions"))
            print(json.dumps({"brief": original, "stages": {k: len(v) for k, v in stages.items()},
                              "grammar": plan.get("cascade_captions")}))
            return
        looked = []
        if not os.environ.get("NO_LOOK") and not plan.get("firsts"):
            # The ladder (cascade.py): free checks first, pictures last and per open moment.
            contradicts = ask_contradictions(reader, key, brief, heads)
            plan["ladder_contradicts"] = [": ".join(c) for c in sorted(contradicts)]

            def looker(refs):
                return look(reader, config, library, plan, refs, anchors, score)

            kept, looked, plan["ladder"] = ladder(looker, library, plan, kept, unsure, uncaptioned & pool,
                                                  anchors & pool, score, heads, contradicts)
        elif not os.environ.get("NO_LOOK"):
            # Only what text could not settle: unsure captions, forwarded photos without one, and
            # OCR anchors (whose letters, not captions, put them here).
            seen, looked = look(reader, config, library, plan, set(unsure) | (uncaptioned & pool) | (anchors & pool),
                                anchors, score)
            # Calibrate the text "yes" on a random sample it produced (the cascade pattern): trusted
            # when the photos agree; otherwise the yeses are looked at too, best-ranked first within
            # the budget, and only what the photo confirms stays (text yes kept 36 bad cars, 09-27).
            import random as _random

            text_yes = sorted(kept)
            sample = _random.Random(11).sample(text_yes, min(CALIBRATION, len(text_yes)))
            confirmed, sample_log = look(reader, config, library, plan, set(sample), set(), score)
            agree = len(confirmed) / max(1, len(sample))
            plan["text_yes_agreement"] = round(agree, 2)
            looked += sample_log
            if agree >= TRUST_TEXT or len(text_yes) <= len(sample):
                kept = (set(text_yes) - set(sample)) | set(confirmed) if agree >= TRUST_TEXT else set(confirmed)
            else:
                rest = [i for i in text_yes if i not in sample]
                more, more_log = look(reader, config, library, plan, set(rest), set(), score)
                looked += more_log
                kept = set(confirmed) | set(more)
            kept = sorted(set(kept) | set(seen), key=lambda i: library.rows[i]["taken_at"])
    stages["kept"] = set(kept)
    save_stages(key, original, spec, library, stages, plan.get("ladder"))
    timeline = [f'{library.rows[i]["taken_at"][:10]}: {library.rows[i]["caption"][:110]}'
                for i in kept[:: max(1, len(kept) // 24)]]
    thesis = reader.ask("translate_thesis", key, THESIS, {"owner_request": brief, "timeline": timeline},
                        lambda a: isinstance(a["thesis"], str), 400) if kept else None
    for k in ("_per_item_questions", "_own", "_companions"):
        plan.pop(k, None)
    record = {"brief": original, "english": brief, "spec": spec, "plan": plan, "scope": scope_note,
              "counts": {"window": len(in_window), "scope": len(pool_scope), "subject_matches": len(subject),
                         "ocr_anchors": len(anchors), "uncaptioned": len(uncaptioned & pool), "pool": len(pool),
                         "text_yes": sum(1 for d in decisions if d["decision"] == "match"),
                         "text_unsure": len(unsure), "judged": len(decisions),
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
    intent.write_text(json.dumps({"name": plan.get("title") or brief[:60], "thesis": record["thesis"] or brief,
                                  "asset_ids": [library.rows[i]["asset_id"] for i in kept]}))
    # The pool is the film's whole material, as an album is: no date window around it, and the
    # album length curve over its photographed days (a multi-year date range clamps to 30 s).
    # Owner ruling: free-text films keep forwarded pictures (a club's photos arrive by chat).
    subprocess.run(["/private/tmp/imm-threads/.venv/bin/immich-memories", "generate", "--from-album",
                    f"file:{intent}", "--accept-any-provenance", "--no-render",
                    "--trace-selection", str(intent.with_suffix(".trace.json"))], check=False)


if __name__ == "__main__":
    main()
