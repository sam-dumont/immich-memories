"""Stage by stage against the owner's labels: where does a request's set get good?

usage: THREADS_ROOT=<owner root> python stages_report.py <requests.yaml>

For each request and each recorded stage (scope, pool, caption_read, caption_yes, caption_unsure,
kept): recall = good labels the stage still holds / all good labels; precision = good / labelled
in the stage. Labels are a gauge, never a target: they were drawn from earlier runs' candidates,
so a stage can hold good pictures nobody labelled.
"""

import json
import sys
from pathlib import Path

import yaml

from experiment_data import ROOT

ORDER = ["scope", "pool", "caption_read", "caption_yes", "caption_unsure", "kept"]


def main(spec_path):
    requests = yaml.safe_load(Path(spec_path).read_text())["requests"]
    labels_dir = Path(spec_path).parent / "labels"
    recorded = {}
    for p in (ROOT / "translations").glob("*.stages.json"):
        d = json.loads(p.read_text())
        recorded[d["brief"]] = d
    for req in requests:
        d = recorded.get(req["text"])
        path = labels_dir / f'{req["id"]}.json'
        labels = json.loads(path.read_text()) if path.exists() else {}
        labels = labels.get("verdicts", labels)
        good = {a for a, v in labels.items() if v == "good"}
        print(f'\n{req["id"]}: {len(good)} good / {len(labels)} labelled')
        if not d:
            print("  (no stages recorded)")
            continue
        for name in ORDER:
            held = set(d["stages"].get(name) or ())
            if name not in d["stages"]:
                continue
            labelled = held & set(labels)
            hits = held & good
            recall = len(hits) / len(good) if good else float("nan")
            precision = len(hits) / len(labelled) if labelled else float("nan")
            print(f"  {name:15s} {len(held):6d} photos | recall {recall:5.0%} | precision {precision:5.0%}"
                  f" ({len(hits)} good of {len(labelled)} labelled)")


if __name__ == "__main__":
    main(sys.argv[1])
