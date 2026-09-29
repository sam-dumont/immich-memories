"""Run against an explicitly chosen provider config, using synthetic evidence only."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import yaml

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.cases import cases
from immich_memories.conformance.inventory import discover_sites
from immich_memories.conformance.runtime import run_case, table
from immich_memories.security import write_secret_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, help="private request/reply evidence and incremental results"
    )
    args = parser.parse_args(argv)
    data = yaml.safe_load(args.config.read_text())
    llm = LLMConfig.model_validate(data.get("advanced", {}).get("llm", data.get("llm", {})))
    if not llm.model.strip():
        parser.error("the config must name an LLM model")
    checks = cases(llm)
    covered = set().union(*(case.sites for case in checks))
    missing = discover_sites(Path(__file__).resolve().parents[1]) - covered
    results = []
    for index, case in enumerate(checks, 1):
        print(f"[{index}/{len(checks)}] {case.name}", flush=True)
        results.append(run_case(case, evidence_dir=args.output))
        if args.output is not None:
            rows = [asdict(row) | {"observed": sorted(row.observed)} for row in results]
            write_secret_file(args.output / "results.private.json", json.dumps(rows, indent=2))
            write_secret_file(args.output / "results.private.md", table(results))
    print(table(results), flush=True)
    if missing:
        print("Uncovered call sites:\n" + "\n".join(sorted(missing)))
    return int(bool(missing) or not results or any(not row.valid for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
