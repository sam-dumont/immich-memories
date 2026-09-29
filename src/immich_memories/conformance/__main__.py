"""Run against an explicitly chosen provider config, using synthetic evidence only."""

import argparse
from pathlib import Path

import yaml

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.cases import cases
from immich_memories.conformance.inventory import discover_sites
from immich_memories.conformance.runtime import run_case, table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    data = yaml.safe_load(args.config.read_text())
    llm = LLMConfig.model_validate(data.get("advanced", {}).get("llm", data.get("llm", {})))
    if not llm.model.strip():
        parser.error("the config must name an LLM model")
    checks = cases(llm)
    covered = set().union(*(case.sites for case in checks))
    missing = discover_sites(Path(__file__).resolve().parents[1]) - covered
    results = [run_case(case) for case in checks]
    print(table(results), flush=True)
    if missing:
        print("Uncovered call sites:\n" + "\n".join(sorted(missing)))
    return int(bool(missing) or not results or any(not row.valid for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
