"""Turn any caption bank into the three files Codex's prototype reads, unchanged logic.

usage: build_library.py <annotations.sqlite> <prototype copy dir>

Writes <dir>/data/{corpus,snapshot,recurrence-index}.json. The recurrence profiles
follow /private/tmp/immich-theme-investigation/caption_recurrence_context.py field
for field, so candidate_pool() sees the same shape it saw on the owner's library.
"""

import hashlib
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import median

import nltk
from nltk.corpus import wordnet as wn

bank, root = Path(sys.argv[1]), Path(sys.argv[2])
nltk.data.path.insert(0, str(root / "data/nltk_data"))
nltk.data.path.append("/private/tmp/immich-theme-investigation/nltk_data")
import re
data = root / "data"
data.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(bank.as_uri() + "?mode=ro", uri=True) as db:
    captions = {}
    for asset, text, written in db.execute(
        "SELECT asset_id, text, written_at FROM descriptions ORDER BY written_at"
    ):
        if text and text.strip():
            captions[asset] = text.strip()
    assets = {
        a: (d, city or "", country or "", lat, lon, kind)
        for a, d, city, country, lat, lon, kind in db.execute(
            "SELECT asset_id, taken_at, city, country, latitude, longitude, "
            "COALESCE(media_kind, 'photo') FROM assets"
        )
    }
    people = defaultdict(set)
    for a, p in db.execute(
        "SELECT asset_id, person_id FROM asset_people WHERE person_id IS NOT NULL AND person_id!=''"
    ):
        people[a].add("P" + hashlib.sha256(p.encode()).hexdigest()[:10])

keys = sorted((a for a in captions if a in assets and assets[a][0]), key=lambda a: assets[a][0])

# Same regional aliasing as experiment_data.load_library.
city_coords, city_days = defaultdict(list), defaultdict(set)
for a in keys:
    d, city, country, lat, lon, _ = assets[a]
    if city and country:
        city_days[country, city].add(d[:10])
        if lat is not None and lon is not None:
            city_coords[country, city].append((lat, lon))
centers = {k: (median(p[0] for p in ps), median(p[1] for p in ps)) for k, ps in city_coords.items()}
reps, aliases = [], {}
for k in sorted(city_days, key=lambda k: -len(city_days[k])):
    target = None
    if k in centers:
        lat, lon = centers[k]
        for o in reps:
            if k[0] != o[0] or o not in centers:
                continue
            lat2, lon2 = centers[o]
            km = math.hypot((lat - lat2) * 111.2, (lon - lon2) * 111.2 * math.cos(math.radians((lat + lat2) / 2)))
            if km <= 10:
                target = o
                break
    if target is None:
        reps.append(k)
        target = k
    aliases[k] = target[1]

rows = []
for a in keys:
    d, city, country, _, _, kind = assets[a]
    rows.append({"asset_id": a, "taken_at": d, "caption": captions[a], "media_kind": kind,
                 "city": city, "country": country, "region": aliases.get((country, city), city),
                 "person_refs": sorted(people[a])})
(data / "corpus.json").write_text(json.dumps(rows, ensure_ascii=False))
(data / "snapshot.json").write_text(json.dumps({
    "captions": len(rows), "total_assets": len(assets), "source": str(bank.name),
    "fingerprint": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
    "image_reads": 0, "episode_reads": 0}))

# caption_recurrence_context.py, paths removed.
stop = set("a an the and or but with without of in on at by to for from into onto over under near next while as is are was were be been being has have had do does did this that these those it its their his her our your my image photo photograph picture scene view background foreground closeup someone something thing seen shown shows showing appears appearing appear featuring features feature there here".split())
tagged = [nltk.pos_tag(re.findall(r"[^\W\d_]+|\d+|[^\w\s]", r["caption"])) for r in rows]


@lru_cache(None)
def norm(w, tag):
    p = wn.NOUN if tag.startswith("NN") else wn.VERB if tag.startswith("VB") else wn.ADJ
    return wn.morphy(w, p) or w


posts, labels, types = defaultdict(list), defaultdict(Counter), {}
for i, sent in enumerate(tagged):
    found = {}
    for j, (raw, tag) in enumerate(sent):
        w = raw.casefold()
        if not w.isalpha() or len(w) < 3 or w in stop:
            continue
        found["word:" + w] = w
        types["word:" + w] = "word"
        if tag.startswith(("NN", "VB", "JJ")):
            cat = "noun" if tag.startswith("NN") else "verb" if tag.startswith("VB") else "descriptor"
            k = cat + ":" + norm(w, tag)
            found[k] = w
            types[k] = cat
        if tag.startswith("NN"):
            for length in (2, 3):
                if j + 1 < length:
                    continue
                part = sent[j + 1 - length:j + 1]
                if not all(t.startswith(("NN", "JJ")) and x.isalpha() and len(x) >= 2 and x.casefold() not in stop for x, t in part):
                    continue
                phrase = " ".join(x.casefold() for x, t in part)
                k = "phrase:" + " ".join(norm(x.casefold(), t) for x, t in part)
                found[k] = phrase
                types[k] = "phrase"
    for k, label in found.items():
        posts[k].append(i)
        labels[k][label] += 1

all_days = {r["taken_at"][:10] for r in rows}
profiles = []
for k, refs in posts.items():
    dates = {rows[i]["taken_at"][:10] for i in refs}
    if len(dates) < 2:
        continue
    yd = Counter(d[:4] for d in dates)
    months = Counter(d[:7] for d in dates)
    countries, cities = defaultdict(set), defaultdict(set)
    for i in refs:
        r = rows[i]
        if r["country"]:
            countries[r["country"]].add(r["taken_at"][:10])
        if r["city"]:
            cities[(r["country"], r["city"])].add(r["taken_at"][:10])
    idf = math.log1p(len(all_days) / len(dates))
    profiles.append({
        "key": k, "term": labels[k].most_common(1)[0][0],
        "variants": [w for w, n in labels[k].most_common(5)], "kind": types[k],
        "captions": len(refs), "days": len(dates), "years": dict(sorted(yd.items())),
        "span": [min(dates), max(dates)], "peak_month_share": round(max(months.values()) / len(dates), 3),
        "status": "recurring" if len(dates) >= 4 and len(yd) >= 2 else "sparse",
        "recurrence_score": round(math.log1p(len(dates)) * math.log1p(len(yd)) * idf, 3),
        "countries": [{"name": c, "days": len(ds)} for c, ds in sorted(countries.items(), key=lambda x: -len(x[1]))],
        "places": [{"country": c, "city": ci, "days": len(ds)} for (c, ci), ds in sorted(cities.items(), key=lambda x: -len(x[1]))[:6]],
        "source_refs": refs})
profiles.sort(key=lambda p: (-p["recurrence_score"], p["key"]))
(data / "recurrence-index.json").write_text(json.dumps({"profiles": profiles}, ensure_ascii=False))
print(json.dumps({"captions": len(rows), "assets": len(assets), "profiles": len(profiles),
                  "recurring": sum(p["status"] == "recurring" for p in profiles)}))
