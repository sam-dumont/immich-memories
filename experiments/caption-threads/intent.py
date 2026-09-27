"""Backward thesis: a light sentence names a scope; the pictures in it hold the story.

"The evolution of our house since 2016" never says renovation, facade or scaffolding. The
home does: words over-represented there and bunched into a few weeks are its changes;
words there every year are its baseline. E4B chooses among what was found, then writes
the thesis. Nothing is invented upstream of the pictures.

usage (env as run.sh): python intent.py "<sentence>"  ->  films/<key>.json, then render
"""

import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from experiment_data import ROOT, load_library, save
from immich_memories.config import Config
from model_reader import Reader
from workflow import choose_sources

CELL = (0.001, 0.0015)  # ~110 m x ~105 m in Belgium; home is the cell with the most days
BURST_DAYS, BURST_SHARE, MIN_HOME = 60, 0.5, 5

SCOPE = '''Read the owner's request for a photo film. Is it about the owner's own home (their
house, flat, place, garden at home)? Which years does it state (since/until), if any?
Return JSON {"about_home":boolean,"since":int or null,"until":int or null,"subject":short phrase}.'''

THESIS = '''The owner asked for a film. Below are topics found in the pictures taken inside the
scope of that request: each is a set of words that appear together in captions there, with
the years it appears in and sample captions; and baseline words that appear there every year. Choose the topics
(ids, as "chapters") that belong to the film the owner asked for, and the baseline words worth showing every
year so the change is visible. Then write the film's thesis in two to four plain sentences,
using only what the chapters and captions show. Return JSON
{"chapters":[ids],"baseline":[words from the baseline list],"thesis":string}.'''


def home_refs(library, bank):
    """The most-days location cell and its neighbours, from the bank's GPS (never exported)."""
    with sqlite3.connect(f"file:{bank}?mode=ro", uri=True) as db:
        gps = {a: (la, lo) for a, la, lo in db.execute(
            "SELECT asset_id, latitude, longitude FROM assets WHERE latitude IS NOT NULL")}
    cell = lambda la, lo: (round(la / CELL[0]), round(lo / CELL[1]))
    days = defaultdict(set)
    cells = {}
    for i, r in enumerate(library.rows):
        if r["asset_id"] in gps:
            k = cell(*gps[r["asset_id"]])
            cells[i] = k
            days[k].add(r["taken_at"][:10])
    home = max(days, key=lambda k: len(days[k]))
    near = {(home[0] + a, home[1] + b) for a in (-1, 0, 1) for b in (-1, 0, 1)}
    return {i for i, k in cells.items() if k in near}


def chapters(library, scope):
    """Topics in the scope: over-represented words that share captions, each with a timeline.

    Grouped by what they describe, not by when: renovation recurs across years and is still
    one topic; a birth and a renovation in the same month are two.
    """
    n, m = len(library.rows), len(scope)
    inside = Counter(t for i in scope for t in library.tokens[i])
    terms = {t for t, c in inside.items()
             if c >= 8 and c <= 0.05 * m and (c / m) / (len(library.posts[t]) / n) >= 1.5}
    with_term = {t: {i for i in scope if t in library.tokens[i]} for t in terms}
    edges = []
    ordered = sorted(terms)
    for a_ix, a in enumerate(ordered):
        for b in ordered[a_ix + 1:]:
            co = len(with_term[a] & with_term[b])
            if co >= 4:
                pmi = math.log(co * m / (len(with_term[a]) * len(with_term[b])))
                if pmi >= math.log(3):
                    edges.append((pmi, a, b))
    parent = {t: t for t in terms}
    size = Counter({t: 1 for t in terms})

    def root(t):
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    for pmi, a, b in sorted(edges, reverse=True):
        ra, rb = root(a), root(b)
        if ra != rb and size[ra] + size[rb] <= 20:
            parent[rb] = ra
            size[ra] += size[rb]
    topics = defaultdict(list)
    for t in terms:
        topics[root(t)].append(t)
    groups = []
    for words_ in topics.values():
        if len(words_) < 3:
            continue
        need = 2 if len(words_) >= 4 else 1
        refs = {i for i in scope if len(library.tokens[i] & set(words_)) >= need}
        if len(refs) >= MIN_HOME:
            ds = sorted(library.rows[i]["taken_at"][:10] for i in refs)
            groups.append({"start": ds[0], "terms": sorted(words_, key=lambda t: -len(with_term[t])),
                           "refs": refs, "years": dict(sorted(Counter(d[:4] for d in ds).items()))})
    groups.sort(key=lambda g: -len(g["refs"]))
    groups = groups[:24]
    everywhere = sorted((t for t, c in inside.items() if c >= 20 and len({library.rows[i]["taken_at"][:4]
                         for i in with_term.get(t, ())}) >= 4), key=lambda t: -inside[t])[:40]
    baseline = [(t, [i for i in scope if t in library.tokens[i]]) for t in everywhere]
    return groups, baseline


def sample(library, refs, k=4):
    refs = sorted(refs, key=lambda i: library.rows[i]["taken_at"])
    return [f'{library.rows[i]["taken_at"][:10]}: {library.rows[i]["caption"][:100]}'
            for i in refs[:: max(1, len(refs) // k)][:k]]


def main():
    brief = sys.argv[1]
    key = "intent:" + hashlib.sha256(brief.encode()).hexdigest()[:16]
    library, reader = load_library(), Reader()
    config = Config.from_yaml(Path.home() / ".immich-memories/config.yaml")

    def valid_scope(a):
        assert isinstance(a["about_home"], bool)

    scope_plan = reader.ask("intent_scope", key, SCOPE, {"owner_request": brief}, valid_scope, 200)
    if not (scope_plan or {}).get("about_home"):
        raise SystemExit("this probe only resolves home scopes; use film.py for the rest")
    since, until = scope_plan.get("since") or 1, scope_plan.get("until") or 9999
    bank = os.environ.get("BANK") or config.editorial.resolve_annotation_database(config.cache.cache_path)
    scope = {i for i in home_refs(library, bank)
             if since <= int(library.rows[i]["taken_at"][:4]) <= until}
    groups, baseline = chapters(library, scope)
    offered = [{"id": j, "years": g["years"], "words": g["terms"][:12], "pictures": len(g["refs"]),
                "captions": sample(library, g["refs"])} for j, g in enumerate(groups)]
    words_every_year = [t for t, _ in baseline]

    def valid_thesis(a):
        assert set(a["chapters"]) <= {c["id"] for c in offered}
        assert set(a["baseline"]) <= set(words_every_year) and isinstance(a["thesis"], str)

    answer = reader.ask("intent_thesis", key, THESIS,
                        {"owner_request": brief, "chapters": offered, "baseline": words_every_year},
                        valid_thesis, 900)
    if not answer:
        raise SystemExit("E4B returned no valid thesis")
    pool = set().union(*(groups[j]["refs"] for j in answer["chapters"])) if answer["chapters"] else set()
    per_year = defaultdict(list)
    for t, refs in baseline:
        if t in answer["baseline"]:
            for i in refs:
                per_year[library.rows[i]["taken_at"][:4]].append(i)
    for year, refs in per_year.items():
        pool |= set(sorted(set(refs), key=lambda i: library.rows[i]["taken_at"])[:: max(1, len(set(refs)) // 6)][:6])
    pool = sorted(pool, key=lambda i: library.rows[i]["taken_at"])[:240]
    decisions = choose_sources(reader, library, key, f"{brief}\nThesis: {answer['thesis']}", pool)
    kept = [d["ref"] for d in decisions if d["decision"] == "match"]
    ids = [library.rows[i]["asset_id"] for i in sorted(kept, key=lambda i: library.rows[i]["taken_at"])]
    record = {"brief": brief, "scope": {"home_pictures": len(scope), "since": since, "until": until},
              "chapters": [o | {"chosen": o["id"] in answer["chapters"]} for o in offered],
              "baseline_offered": words_every_year, "baseline_chosen": answer["baseline"],
              "thesis": answer["thesis"], "pool": len(pool), "kept": len(ids),
              "kept_by_year": dict(sorted(Counter(library.rows[i]["taken_at"][:4] for i in kept).items()))}
    save(ROOT / "intents" / f"{key[7:]}.json", record)
    print(json.dumps({k: v for k, v in record.items() if k != "chapters"}, ensure_ascii=False))
    for o in record["chapters"]:
        print(("CHOSEN " if o["chosen"] else "       ") + f'{o["pictures"]:4} {o["words"][:9]} {o["years"]}')
    if os.environ.get("FILM_DRY") or len(ids) < 5:
        return
    spec = ROOT / "films" / f"{key[7:]}.json"
    spec.parent.mkdir(parents=True, exist_ok=True)
    title = scope_plan.get("subject") or brief[:60]
    spec.write_text(json.dumps({"name": title, "brief": brief, "thesis": answer["thesis"], "asset_ids": ids}))
    subprocess.run(["/private/tmp/imm-threads/.venv/bin/immich-memories", "generate",
                    "--from-album", f"file:{spec}", "--title", title], check=False)


if __name__ == "__main__":
    main()
