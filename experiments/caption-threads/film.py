"""Sentence -> checked sources -> in-memory album (`--from-album file:`) -> film.

usage: run.sh-style env (THREADS_ROOT, HOME=<household captions-home>), then
    python film.py "<owner sentence>"

Nothing is written to Immich. Restricted to the test Immich while this is a probe.
"""

import json
import subprocess
import sys
from pathlib import Path

from experiment_data import ROOT, load_library
from immich_memories.config import Config
from model_reader import Reader
from query import find

TEST_IMMICH = "http://10.2.254.58:2283"


def main():
    brief = sys.argv[1]
    config = Config.from_yaml(Path.home() / ".immich-memories/config.yaml")
    if config.immich.url.rstrip("/") != TEST_IMMICH:
        raise SystemExit("film.py only writes albums to the test Immich")
    result = find(Reader(), load_library(), brief, 48)
    candidates = result.get("handoff", {}).get("candidates", [])
    ids = [e["asset_id"] if isinstance(e, dict) else e.asset_id
           for c in candidates for e in (c["evidence"] if isinstance(c, dict) else c.evidence)]
    summary = {"brief": brief, "status": result["status"], "plan": result.get("plan"),
               "sources": len(ids)}
    if not ids:
        print(json.dumps(summary, ensure_ascii=False))
        return
    title = result.get("judgment", {}).get("title") or result["plan"]["title"]
    spec = ROOT / "films" / f"{result['key'][8:]}.json"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(json.dumps({"name": title, "brief": brief, "asset_ids": ids}))
    summary |= {"title": title, "spec": str(spec)}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    wrapper = "/private/tmp/imm-threads/.venv/bin/immich-memories"
    # The thread is the curation: every checked source is owner-required, so the
    # editor dedupes and orders instead of re-judging the pool as a period.
    includes = [arg for i in ids for arg in ("--include", i)]
    subprocess.run([wrapper, "generate", "--from-album", f"file:{spec}", "--title", title,
                    *includes], check=False)


if __name__ == "__main__":
    main()
