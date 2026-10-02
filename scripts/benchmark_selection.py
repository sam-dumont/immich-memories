"""Compare cached selection algorithms on portable synthetic fixtures, without media or models.

Run each variant in a fresh process. A baseline source file can be exported with
`git show main:src/immich_memories/analysis/editorial_story_shortlist.py`.
Results are planner timings, not whole-film or real-library measurements.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import importlib.util
import json
import os
import platform
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace


def samples(work, repeat):
    """Keep individual unprofiled timings; never infer speed from cProfile."""
    durations = []
    value = None
    for _ in range(repeat):
        started = time.perf_counter()
        value = work()
        durations.append(time.perf_counter() - started)
    return value, {"samples_seconds": durations, "median_seconds": statistics.median(durations)}


def install_baseline(path):
    """Restore both former hot paths without changing any prompt serializer."""
    from immich_memories.analysis import editorial_story_carriers, editorial_story_shortlist

    spec = importlib.util.spec_from_file_location("selection_baseline", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    editorial_story_carriers.nearby_picture_alternatives = module.nearby_picture_alternatives
    editorial_story_shortlist.nearby_picture_alternatives = module.nearby_picture_alternatives
    from immich_memories.analysis import editorial_structure_planner

    def pretty(payload, **options):
        options.pop("separators", None)
        return json.dumps(payload, **{**options, "indent": 1})

    editorial_structure_planner.json = SimpleNamespace(dumps=pretty)


def main():
    """Run a benchmark in an isolated disposable store."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--groups", type=int, default=300)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    if args.repeat < 1 or args.groups < 2:
        parser.error("repeat must be positive and groups at least two")
    startup = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="selection-benchmark-") as folder:
        root = Path(folder)
        # Import and migrations must never discover the operator's live store.
        os.environ["IMMICH_MEMORIES_DATABASE_URL"] = f"sqlite:///{root / 'store.db'}"
        os.environ["IMMICH_MEMORIES_IMPORT_FROM"] = str(root / "legacy")
        os.environ["IMMICH_MEMORIES_CACHE__DIRECTORY"] = str(root / "cache")
        measure(args, root, startup)


def measure(args, root, startup):
    """Warm judgments once, then compare identical complete planner decisions."""
    from tests.test_editorial_duration_planner_integration import run, semantic_plan
    from tests.test_editorial_shortlist_scaling import capture_groups
    from tests.test_editorial_story_first_planner import StoryJudge, make_source

    from immich_memories.analysis.editorial_story_shortlist import nearby_picture_alternatives

    if args.baseline_source:
        install_baseline(args.baseline_source)
        from immich_memories.analysis.editorial_story_shortlist import nearby_picture_alternatives

    choices, units = capture_groups(args.groups)
    units = dict(units)  # Counted lookups belong in the regression test, not timings.
    _, shortlist = samples(
        lambda: nearby_picture_alternatives(choices[::2], choices, units, starred=lambda _: False),
        args.repeat,
    )
    source = make_source(root, seconds=180, occasions=args.groups, pictures=12)
    judge = StoryJudge()
    warmup_started = time.perf_counter()
    run(source, judge)
    warmup_seconds = time.perf_counter() - warmup_started
    startup_seconds = (
        time.perf_counter() - startup - warmup_seconds - sum(shortlist["samples_seconds"])
    )
    plans = []
    prompt_digests = []

    def selection():
        reader = StoryJudge(judge.bank, require_hits=True)
        plan = semantic_plan(run(source, reader))
        plans.append(hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest())
        prompts = [(c["stage"], c["prompt"]) for c in reader.calls]
        prompt_digests.append(hashlib.sha256(json.dumps(prompts).encode()).hexdigest())
        return plan

    plan, planner = samples(selection, args.repeat)
    assert len(set(plans)) == len(set(prompt_digests)) == 1
    if args.profile:
        profiler = cProfile.Profile()
        profiler.runcall(selection)
        profiler.dump_stats(str(args.output.with_suffix(".pstats")))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {
        "scope": "synthetic cached planner; no media, models, network or rendering",
        "variant": "baseline" if args.baseline_source else "indexed",
        "python": platform.python_version(),
        "machine": platform.machine(),
        "system": platform.system(),
        "groups": args.groups,
        "pictures": len(source.assets),
        "carriers": len(plan["carriers"]),
        "startup_and_fixture_seconds": startup_seconds,
        "warmup_seconds": warmup_seconds,
        "shortlist": shortlist,
        "planner": planner,
        "decision_sha256": plans[0],
        "prompt_sha256": prompt_digests[0],
        "peak_rss_mib": rss / (1024**2 if sys.platform == "darwin" else 1024),
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
