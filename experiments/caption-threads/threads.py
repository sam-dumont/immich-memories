"""Discovery in one pass: arithmetic proposes, E4B compares, only winners get source checks.

Replaces nominate (a yes/no per subject that kept 40 of 40) + refinement of 40 threads
+ pick. Roughly 60 E4B calls instead of ~185.

  1. candidate_pool: recurring caption subjects, no model
  2. gates: enough days and years, not one burst
  3. merge on shared pictures: a subject whose matched captions mostly sit inside a
     bigger subject's is that subject told another way (gallop, jockey, mane -> horse)
  4. heats: E4B picks <=2 of 8, five differently drawn rounds, keep >=2 wins
  5. refine: E4B checks the winners' sources; places take their own lane

usage (env as run.sh): python threads.py  ->  THREADS_ROOT/data/threads-v2.json
"""

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor

from experiment_data import ROOT, candidate_pool, load_library, save
from model_reader import Reader
from pick import HEAT, HEAT_PROMPT, ROUNDS, is_burst, places, spread
from workflow import refine

MIN_DAYS_YEARS = 3
KEEP_WINS, MAX_THREADS = 3, 12
GROUP_PROMPT = '''These are threads found in one person's photo library, each a possible film.
Group together threads that are the same part of this person's life seen from different
angles (one hobby, one animal, one place). Keep different subjects apart. Order the groups
from the film this person would most want to watch to the least, and give each group a
warm, specific title. Return JSON {"groups":[{"title":string,"ids":[ids]}]}.'''
CONTAINED = 0.6  # share of the smaller subject's pictures that sit inside the bigger one
# Lexical classes that describe any picture: they may be absorbed, never absorb.
NEVER_ABSORB = {"noun.person", "noun.attribute", "noun.shape", "noun.body", "noun.location",
                "noun.object", "unclassified", "verb.stative"}


def gated(library, pool):
    kept = []
    for c in pool:
        refs = set(c.get("retrieval_refs") or c["refs"])
        years = {library.rows[i]["taken_at"][:4] for i in refs}
        if c["operator"] == "geographic_variation":
            if len({library.rows[i].get("country") for i in refs} - {""}) >= 3:
                kept.append(c | {"pics": refs})
            continue
        if len(years) < MIN_DAYS_YEARS or is_burst(library, refs):
            continue
        kept.append(c | {"pics": refs})
    return kept


def merge(pool):
    pool = sorted(pool, key=lambda c: -len(c["pics"]))
    units = []
    for c in pool:
        home = next((u for u in units
                     if u["operator"] == c["operator"] != "geographic_variation"
                     and u.get("domain") not in NEVER_ABSORB
                     and len(c["pics"] & u["pics"]) / len(c["pics"]) >= CONTAINED), None)
        if home:
            home["merged"].append(c["anchor"])
        else:
            units.append(c | {"merged": []})
    return units


def as_thread(library, u, i):
    refs = u["pics"]
    title = u["anchor"] if not u["merged"] else f'{u["anchor"]} ({", ".join(u["merged"][:4])})'
    years = sorted({library.rows[r]["taken_at"][:4] for r in refs})
    return {"id": i, "title": title, "years": f"{years[0]}-{years[-1]} ({len(years)} years)",
            "pictures": len(refs), "captions": spread(library, refs, 4), "places": places(library, refs)}


def heats(reader, library, units):
    wins = {}
    for round_ in range(ROUNDS):
        order = units[:]
        random.Random(11 + round_).shuffle(order)
        for start in range(0, len(order), HEAT):
            ids = dict(enumerate(order[start:start + HEAT]))

            def valid(a, ids=ids):
                assert len(a["picked"]) <= 2 and all(p["id"] in ids for p in a["picked"])

            answer = reader.ask("thread_heat", f"heat:{round_}:{start}", HEAT_PROMPT,
                                [as_thread(library, u, i) for i, u in ids.items()], valid, 600)
            for p in (answer or {"picked": []})["picked"]:
                u = ids[p["id"]]
                w = wins.setdefault(u["key"], {"unit": u, "wins": 0, "title": p["title"], "why": p["why"]})
                w["wins"] += 1
    # With ~100 threads and 2 picks per heat, two wins can be the draw: admit only
    # threads the model keeps choosing, and never more than a small model can group.
    kept = [w for w in wins.values() if w["wins"] >= KEEP_WINS]
    return sorted(kept, key=lambda w: (-w["wins"], -len(w["unit"]["pics"])))[:MAX_THREADS]


def checked(reader, library, w):
    u, refs = w["unit"], sorted(w["unit"]["pics"])
    candidate = {"key": u["key"], "anchor": u["anchor"], "operator": u["operator"],
                 **library.facts(refs), "context": library.context(refs),
                 "witnesses": library.witnesses(refs, 12)}
    nomination = {"title": w["title"], "hypothesis": w["why"], "unresolved_claims": []}
    return refine(reader, library, candidate, nomination)


def main():
    started = time.monotonic()
    library, reader = load_library(), Reader()
    calls_before = len(list((ROOT / "calls").glob("*.json")))
    pool = gated(library, candidate_pool(library))
    units = merge(pool)
    travel = [u for u in units if u["operator"] == "geographic_variation"]
    subjects = [u for u in units if u["operator"] != "geographic_variation"]
    winners = heats(reader, library, subjects) + [
        {"unit": u, "wins": "-", "title": "Travels across the years",
         "why": "Pictures in several countries, returned to across years."} for u in travel]
    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(lambda w: checked(reader, library, w), winners))
    films = []
    for w, r in zip(winners, results):
        sources = r.get("sources", [])
        if len(sources) < 5:
            continue
        films.append({"film_title": w["title"], "wins": w["wins"], "why": w["why"],
                      "subject": w["unit"]["anchor"], "merged": w["unit"]["merged"],
                      "matched": len(w["unit"]["pics"]), "checked": len(sources),
                      "years": sorted({s["date"][:4] for s in sources}),
                      "asset_ids": [s["asset_id"] for s in sources],
                      "sample": [s["caption"][:120] for s in sources[:: max(1, len(sources) // 3)]][:3]})
    travels = [f for f in films if f["wins"] == "-"]
    ids = dict(enumerate(f for f in films if f["wins"] != "-"))

    def valid_groups(a):
        seen = [i for g in a["groups"] for i in g["ids"]]
        assert set(seen) <= set(ids) and len(seen) == len(set(seen))

    # Words cannot tell that "horseback" and "horse" are one story; the model can,
    # given the titles side by side. Each group becomes one film.
    answer = reader.ask("thread_groups", "groups", GROUP_PROMPT,
                        [{"id": i, "title": f["film_title"], "subject": f["subject"],
                          "also": f["merged"][:4], "years": f"{f['years'][0]}-{f['years'][-1]}",
                          "captions": [c for c in f["sample"]]} for i, f in ids.items()],
                        valid_groups, 700) if len(ids) > 1 else None
    groups = (answer or {"groups": [{"title": f["film_title"], "ids": [i]} for i, f in ids.items()]})["groups"]
    grouped = {i for g in groups for i in g["ids"]}
    groups += [{"title": f["film_title"], "ids": [i]} for i, f in ids.items() if i not in grouped]
    ranked = []
    for g in groups:
        members = [ids[i] for i in g["ids"]]
        if not members:
            continue
        assets = list(dict.fromkeys(a for m in members for a in m["asset_ids"]))
        ranked.append(members[0] | {"film_title": g.get("title") or members[0]["film_title"],
                                    "members": [m["film_title"] for m in members],
                                    "checked": len(assets), "asset_ids": assets,
                                    "years": sorted({y for m in members for y in m["years"]})})
    ranked += [t | {"members": [t["film_title"]]} for t in travels]
    save(ROOT / "data/threads-v2.json", {"pool": len(pool), "units": len(units),
                                         "winners": len(winners), "films": ranked,
                                         "seconds": round(time.monotonic() - started),
                                         "new_model_calls": len(list((ROOT / "calls").glob("*.json"))) - calls_before})
    print(json.dumps({"seconds": round(time.monotonic() - started),
                      "new_model_calls": len(list((ROOT / "calls").glob("*.json"))) - calls_before,
                      "subjects": len(pool), "after_merge": len(units), "winners": len(winners),
                      "films": len(ranked)}))
    for f in ranked:
        yrs = f["years"]
        print(f'{f["film_title"][:46]:46} {yrs[0]}-{yrs[-1]} {f["checked"]:3} pics <- {[m[:24] for m in f["members"]]}')


if __name__ == "__main__":
    main()
