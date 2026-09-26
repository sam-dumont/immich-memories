"""Choose threads by comparison, not by asking E4B yes/no about each one alone.

A yes/no judge kept 40 of 40 threads on the knitter household ("Instances of
Capture", "rolling features"). Asked to choose between threads it sees side by
side, a small model has to spend its judgment on the difference.

  1. arithmetic: drop threads too thin to film, merge threads sharing their pictures
  2. heats: E4B sees 8 threads at a time and picks at most 2, or none
  3. final: E4B orders the heat winners

usage (env as run.sh): python pick.py  ->  THREADS_ROOT/data/picked.json
"""

import json
import math
import random
from collections import Counter

from experiment_data import ROOT, load_library, save
from model_reader import Reader

MIN_SOURCES, MIN_YEARS, MERGE_SIMILARITY, HEAT, ROUNDS = 5, 3, 0.35, 8, 2

HEAT_PROMPT = '''These are candidate threads found in one person's photo library. Each has
a working title, the years it spans and captions of pictures spread across that span.
Which of them would make a short film this person would want to watch about their own
life: something they did, made, cared for or kept going back to over the years?
Pick AT MOST 2. Pick none if none qualifies. A thread whose captions only share a
colour, a texture, a shape, a word or a common background object does not qualify.
Return JSON {"picked":[{"id":id,"title":a warm, specific film title,"why":one sentence}]}.'''

FINAL_PROMPT = '''These threads each won a heat. Order them from the film this person
would most want to watch to the least. Drop any that describe the same subject as a
better one. Return JSON {"order":[ids]}.'''


def refs_of(result):
    return {s["ref"] for s in result.get("sources", [])}


def spread(library, refs, n=3):
    rows = sorted(refs, key=lambda i: library.rows[i]["taken_at"])
    step = max(1, len(rows) // n)
    return [f'{library.rows[i]["taken_at"][:4]}: {library.rows[i]["caption"][:140]}'
            for i in rows[::step][:n]]


def candidates(library):
    threads = []
    for path in sorted((ROOT / "results").glob("*.json")):
        r = json.loads(path.read_text())
        refs = refs_of(r)
        years = {library.rows[i]["taken_at"][:4] for i in refs}
        if r.get("operator") == "owner_request" or len(refs) < MIN_SOURCES or len(years) < MIN_YEARS:
            continue
        threads.append({"key": r["key"], "title": (r.get("judgment") or {}).get("title", r["anchor"]),
                        "refs": refs, "years": sorted(years)})
    threads.sort(key=lambda t: -len(t["refs"]))
    # Two threads are one subject when their pictures are described in the same
    # words. Sampled sources rarely share pictures, so overlap of IDs misses this.
    n = len(library.rows)
    for t in threads:
        counts = Counter(w for i in t["refs"] for w in library.tokens[i])
        t["vector"] = {w: c * math.log(n / len(library.posts[w])) for w, c in counts.items()}
    merged = []
    for t in threads:
        home = next((m for m in merged if cosine(t["vector"], m["vector"]) >= MERGE_SIMILARITY), None)
        if home:
            home["refs"] |= t["refs"]
            home["merged"].append(t["title"])
            home["years"] = sorted(set(home["years"]) | set(t["years"]))
        else:
            merged.append(t | {"merged": []})
    return merged


def cosine(a, b):
    dot = sum(v * b.get(w, 0) for w, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())) or 1)


def show(library, t, i):
    return {"id": i, "title": t["title"], "also": t["merged"][:3],
            "years": f'{t["years"][0]}-{t["years"][-1]} ({len(t["years"])} years)',
            "pictures": len(t["refs"]), "captions": spread(library, t["refs"])}


def main():
    library, reader = load_library(), Reader()
    pool = candidates(library)
    # Every thread runs in ROUNDS differently drawn heats, so one strong neighbour
    # cannot knock a good thread out on its own.
    winners = {}
    for round_ in range(ROUNDS):
        order = pool[:]
        random.Random(7 + round_).shuffle(order)
        for start in range(0, len(order), HEAT):
            ids = dict(enumerate(order[start:start + HEAT]))

            def valid(a, ids=ids):
                assert len(a["picked"]) <= 2 and all(p["id"] in ids for p in a["picked"])

            answer = reader.ask("pick_heat", f"heat:{round_}:{start}", HEAT_PROMPT,
                                [show(library, t, i) for i, t in ids.items()], valid, 600)
            for p in (answer or {"picked": []})["picked"]:
                t = ids[p["id"]]
                winners.setdefault(t["key"], t | {"film_title": p["title"], "why": p["why"]})
    winners = list(winners.values())
    ids = {i: t for i, t in enumerate(winners)}

    def valid_order(a):
        assert set(a["order"]) <= set(ids)

    order = reader.ask("pick_final", "final", FINAL_PROMPT,
                       [show(library, t, i) | {"film_title": t["film_title"]} for i, t in ids.items()],
                       valid_order, 400) if len(ids) > 1 else {"order": list(ids)}
    ranked = [ids[i] for i in (order or {"order": list(ids)})["order"]]
    out = [{"film_title": t["film_title"], "why": t["why"], "found_as": t["title"],
            "merged": t["merged"], "years": t["years"], "pictures": len(t["refs"]),
            "asset_ids": [library.rows[i]["asset_id"] for i in sorted(t["refs"])]} for t in ranked]
    save(ROOT / "data/picked.json", {"considered": len(pool), "heat_winners": len(winners),
                                     "threads": out})
    print(json.dumps({"considered": len(pool), "winners": len(winners)}))
    for t in out:
        print(f'{t["film_title"][:50]:50} {t["years"][0]}-{t["years"][-1]} {t["pictures"]:3} '
              f'(found as: {t["found_as"][:40]}; +{len(t["merged"])} merged)')


if __name__ == "__main__":
    main()
