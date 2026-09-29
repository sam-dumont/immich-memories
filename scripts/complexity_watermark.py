"""Hold the cognitive-complexity backlog to a watermark that carries no line numbers.

complexipy's own snapshot records where each function starts and ends, so any edit
above a listed function changed the file: every branch carried unrelated churn and
open PRs conflicted on it (#1550). The watermark keys each over-limit function by
file and qualified name, which only moves when the code it names does.

Rules, as before: no new function over the limit, a recorded one may only go down,
and the file is rewritten only by a passing run that tightened it.

Usage: complexity_watermark.py [--watermark PATH] RESULTS_JSON
where RESULTS_JSON is `complexipy --failed --output-json` output. Exit 0 pass,
1 a new or worse violation, 2 no usable results from the analyzer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

LIMIT = 15
DEFAULT_WATERMARK = Path(__file__).resolve().parents[1] / "complexity-watermark.json"

Watermark = dict[str, dict[str, list[int]]]


def watermark_of(rows: list[dict]) -> Watermark:
    """The over-limit functions complexipy reported, by file, name and complexity."""
    found: Watermark = {}
    for row in rows:
        if row["complexity"] > LIMIT:
            found.setdefault(row["path"], {}).setdefault(row["function_name"], []).append(
                row["complexity"]
            )
    return found


def violations_of(recorded: Watermark, current: Watermark) -> list[str]:
    """The over-limit functions the recorded watermark does not allow.

    Functions sharing a name in one file (overloads, nested helpers) are compared worst
    against worst, so a second one over the limit is a new violation, never absorbed.
    """
    violations = []
    for path, functions in sorted(current.items()):
        for name, found in sorted(functions.items()):
            allowed = sorted(recorded.get(path, {}).get(name, []), reverse=True)
            for index, value in enumerate(sorted(found, reverse=True)):
                if index >= len(allowed):
                    violations.append(f"{path}: {name} is {value}, over {LIMIT} and new")
                elif value > allowed[index]:
                    violations.append(f"{path}: {name} rose to {value} from {allowed[index]}")
    return violations


def render(watermark: Watermark) -> str:
    """Sorted JSON with one function per line, so a change to one is a one-line diff."""
    files = []
    for path, functions in sorted(watermark.items()):
        if not functions:
            continue
        lines = [
            f"    {json.dumps(name)}: {json.dumps(sorted(values, reverse=True))}"
            for name, values in sorted(functions.items())
        ]
        files.append(f"  {json.dumps(path)}: {{\n" + ",\n".join(lines) + "\n  }")
    return "{\n" + ",\n".join(files) + "\n}\n" if files else "{}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--watermark", type=Path, default=DEFAULT_WATERMARK)
    parser.add_argument("results", type=Path, nargs="*")
    args = parser.parse_args(argv)
    if len(args.results) != 1 or not args.results[0].is_file():
        print("Cognitive complexity gate FAILED: complexipy wrote no results file")
        return 2
    rows = json.loads(args.results[0].read_text())
    recorded = json.loads(args.watermark.read_text()) if args.watermark.exists() else {}
    # A passing run holds every function at or under its record, so what it found is the
    # tightened watermark.
    earned = watermark_of(rows)
    violations = violations_of(recorded, earned)
    if violations:
        print("\n".join(violations))
        print("Cognitive complexity gate FAILED: extract a helper from each function above")
        return 1
    if render(earned) != render(recorded):
        args.watermark.write_text(render(earned))
        print("Cognitive complexity: passed, and the watermark tightened")
    else:
        print("Cognitive complexity: passed (no new violations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
