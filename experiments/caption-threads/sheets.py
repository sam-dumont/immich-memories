"""Contact sheets for the latest selection of each request: one private, self-contained HTML.

usage: THREADS_ROOT=... HOME=<home with the Immich config> python sheets.py <prompts file> <out.html>
Reads the translations records and the owner's Immich (thumbnails only, read-only).
"""

import base64
import html
import io
import json
import sys
from pathlib import Path

import httpx
from PIL import Image

from experiment_data import ROOT
from immich_memories.config import Config

PER_REQUEST = 40


def latest(brief):
    records = [json.loads(p.read_text()) for p in (ROOT / "translations").glob("*.json")
               if not p.name.endswith("intent.json")]
    records = [r for r in records if r.get("brief") == brief]
    return max(records, key=lambda r: r.get("_mtime", 0), default=None) if records else None


def thumb(client, asset_id):
    try:
        raw = client.get(f"/api/assets/{asset_id}/thumbnail?size=thumbnail").content
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        image.thumbnail((220, 220))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=72)
        return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()
    except Exception:  # a missing thumbnail must not sink the sheet
        return ""


def main():
    prompts = [l.strip() for l in Path(sys.argv[1]).read_text().splitlines() if l.strip() and not l.startswith("#")]
    config = Config.from_yaml(Path.home() / ".immich-memories/config.yaml")
    captions = {}
    for row in json.loads((ROOT / "data/corpus.json").read_text()):
        captions[row["asset_id"]] = (row["taken_at"][:10], row["caption"])
    for p in (ROOT / "translations").glob("*.json"):
        if not p.name.endswith("intent.json"):
            data = json.loads(p.read_text())
            data["_mtime"] = p.stat().st_mtime
            p_cache[p] = data
    sections = []
    with httpx.Client(base_url=config.immich.url, headers={"x-api-key": config.immich.api_key}, timeout=60) as c:
        for brief in prompts:
            r = max((d for d in p_cache.values() if d.get("brief") == brief), key=lambda d: d["_mtime"], default=None)
            if not r:
                sections.append(f"<section><h2>{html.escape(brief)}</h2><p>No run yet.</p></section>")
                continue
            ids = sorted(r.get("asset_ids") or [], key=lambda a: captions.get(a, ("9999", ""))[0])
            shown = ids[:: max(1, len(ids) // PER_REQUEST)][:PER_REQUEST]
            plan = r["plan"]
            facts = {"subject": plan.get("subject"), "photo question": plan.get("visual_questions"),
                     "filters": plan.get("filters"), "scope": plan.get("scope"), "people": len(plan.get("people") or []),
                     "text to read": plan.get("read_text"), "counts": r.get("counts"), "by year": r.get("kept_by_year")}
            tiles = []
            for a in shown:
                date, cap = captions.get(a, ("", "(forwarded, no caption)"))
                tiles.append(f'<figure><img src="{thumb(c, a)}" alt=""><figcaption><b>{date}</b> '
                             f'{html.escape(cap[:110])}</figcaption></figure>')
            sections.append(f"<section><h2>{html.escape(brief)}</h2><p class=meta>{len(ids)} kept, "
                            f"showing {len(shown)}</p><pre>{html.escape(json.dumps(facts, ensure_ascii=False, indent=1))}</pre>"
                            f"<div class=grid>{''.join(tiles)}</div></section>")
    page = f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Free-text selections</title><style>
:root{{--bg:#fafafa;--fg:#1b1b1b;--muted:#666;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141414;--fg:#eee;--muted:#aaa;--card:#1f1f1f}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;margin:0;padding:16px}}
h1{{font-size:20px}} h2{{font-size:17px;margin:28px 0 4px}} .meta{{color:var(--muted);margin:0 0 6px}}
pre{{font-size:11px;background:var(--card);padding:8px;border-radius:6px;overflow-x:auto;white-space:pre-wrap}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}}
figure{{margin:0;background:var(--card);border-radius:6px;overflow:hidden}} img{{width:100%;aspect-ratio:1;object-fit:cover;display:block}}
figcaption{{font-size:11px;padding:4px 6px;color:var(--muted)}}</style></head><body>
<h1>Free-text selections (private, contact sheets, no render)</h1>{''.join(sections)}</body></html>"""
    Path(sys.argv[2]).write_text(page)
    print(sys.argv[2], len(page) // 1024, "KB")


p_cache = {}

if __name__ == "__main__":
    main()
