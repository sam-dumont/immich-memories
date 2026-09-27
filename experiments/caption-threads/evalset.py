"""Labelled request set: candidates to label, and a score for any run.

  python evalset.py candidates <requests.yaml> <out.json>   # what to label, per request
  python evalset.py score <requests.yaml>                    # score the latest run of each request

Labels live next to the request file: labels/<id>.json = {asset_id: "good" | "bad"}.
Expectations are scoring only and never reach a prompt.
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

import yaml

from experiment_data import ROOT

PER_REQUEST = 80


def runs():
    out = {}
    for p in (ROOT / "translations").glob("*.json"):
        if p.name.endswith("intent.json"):
            continue
        r = json.loads(p.read_text())
        r["_mtime"] = p.stat().st_mtime
        if r.get("brief") not in out or out[r["brief"]]["_mtime"] < r["_mtime"]:
            out[r["brief"]] = r
    return out


def corpus():
    return {row["asset_id"]: row for row in json.loads((ROOT / "data/corpus.json").read_text())}


def candidates(spec_path, out_path):
    """Kept picks, visually rejected ones and near-misses, spread across the years: labels on
    all three measure precision and recall, not just what the current version chose."""
    spec, latest, rows = yaml.safe_load(Path(spec_path).read_text()), runs(), corpus()
    rng = random.Random(7)
    result = {}
    for req in spec["requests"]:
        r = latest.get(req["text"])
        if not r:
            continue
        kept = list(r.get("asset_ids") or [])
        looked = [x for x in r.get("looked") or []]
        rejected_caps = {x["caption"][:80] for x in looked if not x["kept"]}
        rejected = [a for a, row in rows.items() if row["caption"][:80] in rejected_caps][:40]
        pool = kept[:]
        rng.shuffle(pool)
        by_year = {}
        for a in kept:
            by_year.setdefault(rows.get(a, {}).get("taken_at", "????")[:4], []).append(a)
        share = max(1, (PER_REQUEST * 2 // 3) // max(1, len(by_year)))
        chosen = [a for y in sorted(by_year) for a in by_year[y][:share]]
        chosen += [a for a in rejected if a not in chosen][: PER_REQUEST - len(chosen)]
        result[req["id"]] = {"text": req["text"], "assets": chosen[:PER_REQUEST],
                             "source": {"kept": len(kept), "rejected_offered": len(rejected)}}
    Path(out_path).write_text(json.dumps(result, indent=1))
    print({k: len(v["assets"]) for k, v in result.items()})


def plan_checks(expect, plan):
    checks = {}
    if "people" in expect:
        checks["people"] = sorted(expect["people"]) == sorted(plan.get("people") or [])
    for k in ("date_from", "date_to"):
        if k in expect:
            got = (plan.get("filters") or {}).get(k)
            checks[k] = (got or None) == expect[k] or (expect[k] is None and not got)
    if "read_text" in expect:
        checks["read_text"] = sorted(t.lower() for t in expect["read_text"]) == sorted(
            t.lower() for t in plan.get("read_text") or [])
    if "scope" in expect:
        checks["scope"] = plan.get("scope") == expect["scope"]
    if "subject_has" in expect:
        words = " ".join(plan.get("subject") or []).lower()
        checks["subject"] = any(w in words for w in expect["subject_has"])
    return checks


def score(spec_path):
    spec, latest = yaml.safe_load(Path(spec_path).read_text()), runs()
    labels_dir = Path(spec_path).parent / "labels"
    rows = corpus()
    for req in spec["requests"]:
        r = latest.get(req["text"])
        if not r:
            print(f'{req["id"]:20} no run')
            continue
        labels = json.loads((labels_dir / f'{req["id"]}.json').read_text()) if (labels_dir / f'{req["id"]}.json').exists() else {}
        kept = set(r.get("asset_ids") or [])
        good = {a for a, v in labels.items() if v == "good"}
        bad = {a for a, v in labels.items() if v == "bad"}
        judged = kept & (good | bad)
        precision = len(kept & good) / len(judged) if judged else None
        recall = len(kept & good) / len(good) if good else None
        checks = plan_checks(req.get("expect") or {}, r.get("plan") or {})
        years = Counter(rows.get(a, {}).get("taken_at", "????")[:4] for a in kept)
        print(f'{req["id"]:20} plan {sum(checks.values())}/{len(checks)} {[k for k, v in checks.items() if not v]} | '
              f'kept {len(kept)} | precision {precision if precision is None else round(precision, 2)} '
              f'(on {len(judged)} labelled) | recall {recall if recall is None else round(recall, 2)} '
              f'(of {len(good)} good) | years {len(years)}')


if __name__ == "__main__":
    {"candidates": lambda: candidates(sys.argv[2], sys.argv[3]), "score": lambda: score(sys.argv[2])}[sys.argv[1]]()
