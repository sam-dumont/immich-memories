"""Sentence -> checked sources -> in-memory album (`--from-album file:`) -> film.

usage: run.sh-style env (THREADS_ROOT, HOME=<household captions-home>), then
    python film.py "<owner sentence>"

Nothing is written to Immich. Restricted to the test Immich while this is a probe.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from experiment_data import ROOT, load_library
from immich_memories.config import Config
from model_reader import Reader
from query import find

TEST_IMMICH = "http://10.2.254.58:2283"


THESIS = '''Write the thesis of a short film from the owner's request and the pictures
found for it (dates and captions, in order). Two to four plain sentences: what the film is
about and how it moves through time. Use only the owner's words and what the captions show;
do not invent names, events or feelings. Return JSON {"thesis":string}.'''


def write_thesis(result, brief):
    """The lens the regular selection reads the pool through: the owner's words plus the timeline."""
    evidence = result.get("handoff", {}).get("candidates", [{}])[0].get("evidence", [])
    step = max(1, len(evidence) // 24)
    timeline = [f'{e["taken_at"][:10]}: {e["caption"][:110]}' for e in evidence[::step]]

    def valid(a):
        assert isinstance(a["thesis"], str) and 20 < len(a["thesis"]) < 900

    answer = READER.ask("thesis", result["key"], THESIS,
                        {"owner_request": brief, "timeline": timeline}, valid, 400)
    return (answer or {}).get("thesis") or brief


def main():
    brief = sys.argv[1]
    config = Config.from_yaml(Path.home() / ".immich-memories/config.yaml")
    # The owner's own library only on explicit request; reads only, nothing written back.
    if config.immich.url.rstrip("/") != TEST_IMMICH and not os.environ.get("OWNER_OK"):
        raise SystemExit("film.py only writes albums to the test Immich")
    global READER
    READER = Reader()
    result = find(READER, load_library(), brief, int(os.environ.get("SAMPLES", 48)))
    candidates = result.get("handoff", {}).get("candidates", [])
    ids = [e["asset_id"] if isinstance(e, dict) else e.asset_id
           for c in candidates for e in (c["evidence"] if isinstance(c, dict) else c.evidence)]
    summary = {"brief": brief, "status": result["status"], "plan": result.get("plan"),
               "sources": len(ids)}
    if len(ids) < 5:  # two stray matches are not a film
        summary["status"] = "too_few_sources" if ids else summary["status"]
        print(json.dumps(summary, ensure_ascii=False))
        return
    title = result.get("judgment", {}).get("title") or result["plan"]["title"]
    spec = ROOT / "films" / f"{result['key'][8:]}.json"
    spec.parent.mkdir(parents=True, exist_ok=True)
    thesis = write_thesis(result, brief)
    spec.write_text(json.dumps({"name": title, "brief": brief, "thesis": thesis, "asset_ids": ids}))
    summary |= {"title": title, "thesis": thesis, "spec": str(spec)}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if os.environ.get("FILM_DRY"):
        return
    wrapper = "/private/tmp/imm-threads/.venv/bin/immich-memories"
    # The pool goes to the regular flow with the thesis as its written subject: the
    # editor selects through that lens and every eligibility check still applies.
    subprocess.run([wrapper, "generate", "--from-album", f"file:{spec}", "--title", title],
                   check=False)


if __name__ == "__main__":
    main()
