"""Cut the same demo month once per tier, for the "One month, three tiers" docs page.

The page compares what Basic, GPU and Full each make of one month of the demo library
(`tests/e2e/fixtures/library`), so each tier runs the production `generate` for real against a
real Immich seeded with the library (`make immich-gate-up` then
`tests.integration.features.real_seed`), the way `scripts/record_demo_runs.py` records the
memory types. Every tier gets its own home, so no store, cache or prepared picture carries from
one tier to the next, and the same bundled track, so the films differ only in what they show.

GPU and Full read the caption server the Apple Silicon setup starts (`caption_base_url`); Full
also reads the model the operator's own config names (`llm` in `~/.immich-memories/config.yaml`),
copied into its home, never printed and never named in the provenance. Nothing else is read
from the operator's home.

It writes the web copy of the film and a contact sheet under `docs-site/static/demo/tiers/`:
one `month.mp4` when every tier rendered the same frames, else one per tier. `provenance.json`
beside them holds the code revision, the software and models, and for each tier the pictures its
cut chose (by fixture file name), its summary, its timings and the decode check.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.record_demo_runs import (  # noqa: E402
    _birth_dates_into,
    _env,
    _household_into,
    _models_into,
    _operator_llm,
)
from tests.features.cli_harness import UserHome, basic_config  # noqa: E402

TIERS = ("basic", "gpu", "full")
OUT = ROOT / "docs-site" / "static" / "demo" / "tiers"
LIBRARY = ROOT / "tests" / "e2e" / "fixtures" / "library" / "library.json"
TRACK = (
    ROOT / "packages/immich-memories-music/immich_memories_music/tracks/calm/calm_acoustic_1.opus"
)
CAPTIONS = "http://127.0.0.1:8092/v1"
# The recorded month of the demo, asked for the way the old page asked: a minute, photos on,
# shared with family, the app's own title.
REQUEST = [
    "--memory-type", "monthly_highlights", "--month", "7", "--year", "2025",
    "--duration", "60", "--include-photos", "--sharing", "family", "--no-llm-title",
    "--music", str(TRACK),
]  # fmt: skip
# A web copy small enough for the docs site: three of them stay under 30 MB.
WEB_BYTES = 9 * 1024 * 1024
_RUN_ID = re.compile(r"\b(\d{8}_\d{6}_[0-9a-f]{4})\b")
SOFTWARE = ("immich-memories", "onnxruntime", "torch", "mlx", "laya-mlx", "immich-memories-music")


def _home(root: Path, tier: str, state: dict[str, Any]) -> UserHome:
    home = UserHome(root)
    config = basic_config(state["url"], state["api_key"], home)
    config["tier"] = tier
    config["output"].update(resolution="720p", quality="medium")
    if tier != "basic":
        config["advanced"]["editorial"] = {"preparation": {"caption_base_url": CAPTIONS}}
    if tier == "full":
        config["llm"] = _operator_llm()
    home.write_config(config)
    _models_into(root)
    _birth_dates_into(state)
    _household_into(home, state)
    return home


def _cli(home: Path, *args: str, log: Path | None = None) -> str:
    command = [str(ROOT / ".venv" / "bin" / "immich-memories"), *args]
    # A wide terminal: `runs story` wraps at the width it is given, and a wrapped summary line
    # loses its indent.
    env = {**_env(home), "COLUMNS": "400"}
    done = subprocess.run(  # noqa: S603
        command, cwd=home, env=env, capture_output=True, text=True, check=False
    )
    if log is not None:
        log.write_text(done.stdout + done.stderr)
    if done.returncode != 0:
        raise SystemExit(f"{' '.join(args[:2])} failed ({done.returncode}); see {log}")
    return done.stdout + done.stderr


def _selected(home: Path, since: float, file_of: dict[str, str]) -> list[str]:
    """The fixture file names the cut chose, in the order the film plays them."""
    projections = [
        p
        for p in (home / ".immich-memories").rglob("render-projection.private.json")
        if p.stat().st_mtime >= since
    ]
    if not projections:
        raise SystemExit("the run wrote no render projection")
    projection = json.loads(max(projections, key=lambda p: p.stat().st_mtime).read_text())
    return [file_of.get(asset, asset) for asset in projection["selected_ids"]]


def _probe(film: Path) -> dict[str, Any]:
    probe = json.loads(
        subprocess.run(  # noqa: S603, S607
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(film)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    decode = subprocess.run(  # noqa: S603, S607
        ["ffmpeg", "-v", "error", "-i", str(film), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "seconds": round(float(probe["format"]["duration"]), 1),
        "streams": [
            [s["codec_type"], s["codec_name"], s.get("width"), s.get("height")]
            for s in probe["streams"]
        ],
        "decode_exit": decode.returncode,
    }


def _web_copy(film: Path, target: Path) -> None:
    """The film re-encoded to fit the docs site: same frames, a bitrate the size allows."""
    seconds = float(
        subprocess.run(  # noqa: S603, S607
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
             str(film)],
            capture_output=True, text=True, check=True,
        ).stdout
    )  # fmt: skip
    video_bits = int(WEB_BYTES * 8 * 0.95 / seconds) - 128_000
    subprocess.run(  # noqa: S603, S607
        ["ffmpeg", "-y", "-v", "error", "-i", str(film), "-c:v", "libx264", "-preset", "slow",
         "-b:v", str(video_bits), "-maxrate", str(video_bits * 2), "-bufsize", str(video_bits * 2),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
         str(target)],
        check=True,
    )  # fmt: skip


def _contact_sheet(film: Path, target: Path) -> None:
    """Four frames of the finished film, a quarter of the way apart, side by side."""
    seconds = _probe(film)["seconds"]
    step = seconds / 5
    subprocess.run(  # noqa: S603, S607
        ["ffmpeg", "-y", "-v", "error", "-i", str(film), "-vf",
         f"fps=1/{step:.3f},scale=480:-1,tile=4x1", "-frames:v", "1", "-q:v", "3", str(target)],
        check=True,
    )  # fmt: skip


_PIPELINE = re.compile(
    r"Full pipeline timing \(\d+ clips, (?P<total>[\d.]+)s total\): "
    r"analysis=(?P<analysis>[\d.]+)s .*generation=(?P<generation>[\d.]+)s"
)


def _frames_md5(film: Path) -> str:
    """What the film shows, frame by frame, at a size encoder noise cannot reach."""
    done = subprocess.run(  # noqa: S603, S607
        ["ffmpeg", "-v", "error", "-i", str(film), "-vf", "scale=160:-1", "-an", "-f", "md5", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip().removeprefix("MD5=")


def _summary(story: str) -> str:
    """The film's one paragraph, as `runs story` prints it under the run line."""
    lines = story.split("\n\n")[0].splitlines()
    body = [line.strip() for line in lines if line.startswith("  ")]
    return " ".join(body)


def record(tier: str, base: Path, state: dict[str, Any], file_of: dict[str, str]) -> dict:
    home = _home(base / tier, tier, state)
    logs = base / tier / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = time.time()
    output = _cli(home.root, "generate", *REQUEST, log=logs / "generate.log")
    wall = round(time.time() - started)
    run_id = _RUN_ID.findall(output)[-1]
    films = sorted(home.videos.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
    if not films or films[-1].stat().st_mtime < started:
        raise SystemExit(f"{tier}: the run made no film; see {logs / 'generate.log'}")
    story = _cli(home.root, "runs", "story", run_id)
    (logs / "story.txt").write_text(story)
    timing = _PIPELINE.search(output)
    return {
        "selected": _selected(home.root, started, file_of),
        "summary": _summary(story),
        "pipeline_seconds": {k: float(v) for k, v in timing.groupdict().items()} if timing else {},
        "wall_seconds": wall,
        "source_film": {"path": str(films[-1]), **_probe(films[-1])},
        "frames_md5": _frames_md5(films[-1]),
    }


def _publish(tiers: dict[str, dict]) -> None:
    """The web copies: one film when every tier rendered the same frames, else one per tier."""
    OUT.mkdir(parents=True, exist_ok=True)
    same = len({t["frames_md5"] for t in tiers.values()}) == 1
    names = {"month": next(iter(tiers))} if same else {tier: tier for tier in tiers}
    for name, tier in names.items():
        web = OUT / f"{name}.mp4"
        _web_copy(Path(tiers[tier]["source_film"].pop("path")), web)
        _contact_sheet(web, OUT / f"{name}-contact.jpg")
        for each in tiers if same else (tier,):
            tiers[each]["film"] = {"path": f"tiers/{name}.mp4", "bytes": web.stat().st_size,
                                   **_probe(web)}  # fmt: skip
    for tier in tiers.values():
        tier["source_film"].pop("path", None)


def _software() -> dict[str, str]:
    versions = {}
    for name in SOFTWARE:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return versions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", type=Path, required=True, help="real_seed's state.json")
    parser.add_argument("--home", type=Path, required=True, help="one home per tier, under it")
    parser.add_argument("--only", nargs="*", choices=TIERS, default=None)
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    library = json.loads(LIBRARY.read_text())
    names = {asset["stem"]: asset["file"] for asset in library}
    file_of = {
        server: names.get(fixture, fixture) for fixture, server in state["asset_ids"].items()
    }
    path = OUT / "provenance.json"
    provenance = json.loads(path.read_text()) if path.exists() else {}
    provenance.update(
        source_sha=subprocess.run(  # noqa: S603, S607
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=ROOT
        ).stdout.strip(),
        software=_software(),
        platform=f"{platform.system()} {platform.machine()}",
        request=[a if a != str(TRACK) else TRACK.name for a in REQUEST],
        services={
            "captioner": "smolvlm2-500m-base-public (gpu, full)",
            # The operator's own model server: which one stays out of a public file.
            "reader": "the operator's own (full)" if "full" in (args.only or TIERS) else None,
        },
    )
    tiers = provenance.setdefault("tiers", {})
    for tier in args.only or TIERS:
        tiers[tier] = record(tier, args.home, state, file_of)
        print(f"{tier}: {len(tiers[tier]['selected'])} shots in {tiers[tier]['wall_seconds']} s",
              flush=True)  # fmt: skip
    _publish(tiers)
    path.write_text(json.dumps(provenance, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
