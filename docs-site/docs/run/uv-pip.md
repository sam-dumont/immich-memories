---
title: uv / pip
---

# uv or pip

For a Mac, a Linux box without Docker, or a checkout you want to hack on. Docker Compose is the
[recommended install](./docker.md); this one gives the same app with your Python.

You need **Python 3.11 or newer** and FFmpeg on your `PATH`:

```bash
brew install ffmpeg        # macOS
sudo apt install ffmpeg    # Debian, Ubuntu
```

## Install

Always with an extra. A bare install has no ONNX Runtime, which even NAS needs for its inexpensive
picture classifiers.

```bash
uv tool install "immich-memories[all]"       # or [all-mac] on Apple Silicon
```

Tell it where Immich is, in `~/.immich-memories/config.yaml` (the key's minimal permissions are on
[the Docker page](./docker.md#the-api-key)):

```yaml
immich:
  url: http://192.168.1.10:2283
  api_key: your-api-key
```

Then fetch the models, check, and start the UI:

```bash
immich-memories models fetch                 # about 140 MB, once
immich-memories preflight                    # Immich, models, output folder, home base
immich-memories ui                           # http://localhost:8080
```

Or with pip, in a virtual environment (not your system Python):

```bash
pip install "immich-memories[all]"          # or [all-mac] on Apple Silicon
```

Quote the spec: zsh reads `[...]` as a glob and fails with `no matches found` otherwise.

To try it without installing anything:
`uvx --from "immich-memories[editorial]" immich-memories ui` (the classifiers only: `[all]` adds
authentication, generated music and the audio extras). To get uv itself: `brew install uv`,
or `curl -LsSf https://astral.sh/uv/install.sh | sh`.

`models fetch` writes the encoder to `~/.immich-memories/models/triage/`, the sensitive-content
detector to `~/.immich-memories/models/detectors/`, the WordNet dictionary to
`~/.immich-memories/models/wordnet/`, and the document classifier into the Hugging Face cache
(`~/.cache/huggingface`, or `advanced.editorial.preparation.detector_cache_dir`). Each is checked
against a SHA-256. It needs the `editorial` extra (every `all*` extra has it).

A cut checks the two ONNX files and the output folder (`~/Videos/Memories` by default,
`output.directory` to move it) before it asks Immich for anything, and stops with
`Run immich-memories models fetch` if a model is missing.
Everything else goes in the same file ([Configuration file](./config-file.md)) or the environment
([Environment variables](./environment-variables.md)). Then [your first film](../get-started/first-film.mdx),
and [who's who](../get-started/who-is-who.md) once: home base and close family.

## Reaching the UI from another machine

With authentication off, `immich-memories ui` listens on `127.0.0.1:8080` only. Turn on basic auth
or OIDC ([Authentication](./authentication.mdx); OIDC needs the `auth` extra, which `[all]` has) and
it listens on every interface. `--host` and `--port` override both (`immich-memories ui --host
0.0.0.0 --port 8080`), and an explicit `--host` wins even with authentication off, so only use it
that way on a network you trust. Behind a reverse proxy, read
[the four proxy settings](./authentication.mdx#behind-a-reverse-proxy-with-tls) first.

## From a checkout

```bash
git clone https://github.com/sam-dumont/immich-video-memory-generator.git
cd immich-video-memory-generator
uv sync --extra editorial      # or --extra all-mac on Apple Silicon
make web-client                # the web UI, built from web/; needs Node 22
uv run immich-memories ui
```

`uv sync` installs into the clone's `.venv` and puts nothing on your `PATH`: inside the clone it is
always `uv run immich-memories ...`. `pip install -e .` works too. A checkout is the only install
that needs Node: the PyPI wheel and the Docker image ship the web client already built. Skip
`make web-client` and the CLI still works, but `/app` only tells you to build the client.

## Extras

| Extra | What it adds |
|---|---|
| `editorial` | ONNX Runtime and Hugging Face Hub, for the context heads and the two detectors. The one you need |
| `editorial-cuda` | The same on a CUDA host. **Replaces** `editorial`, never joins it |
| `mac` | pyobjc bindings (Quartz, Metal, Vision) for hardware probing. Not enough to cut with alone |
| `music` | The bundled royalty-free track library |
| `audio` | Local music metadata (mutagen) for `immich-memories music search` |
| `auth` | OIDC login (authlib) |
| `demucs` | Local Demucs stem separation for music ducking (Torch, about 80 MB of model) |
| `all` | All of the above except `mac` and `editorial-cuda` |
| `all-mac` | `editorial`, `mac`, `music`, `audio` and `demucs`. No `auth`: add `[all-mac,auth]` for OIDC |

Never install `editorial` and `editorial-cuda` together: `onnxruntime` and `onnxruntime-gpu` own
the same import name, and the one that answers is whichever pip wrote last.

GPU title rendering needs no extra: its kernel library is a base dependency wherever it publishes a
wheel ([Title kernels](./hardware.md#title-kernels)). Local ACE-Step music on a Mac is a checkout
job (`make install-acestep`, then `make check-local-audio`): [Generated music](../better/music.md).

exiftool is worth having on an Apple HEIC library: it is the fallback when the Python HDR headroom
parser trips on an unusual file. `brew install exiftool`, or `apt install libimage-exiftool-perl`.

## Daily automation

`immich-memories ui` is usually not running all day on a laptop, so the system scheduler runs the
daily job. One command installs it: a launchd job on macOS, a systemd user timer on Linux, or a
crontab line to paste anywhere else.

```bash
immich-memories auto install --hour 9     # --uninstall removes it
```

The job does not inherit your shell's environment, so keep the Immich URL and key in
`~/.immich-memories/config.yaml`. It refuses to schedule a git worktree or a checkout behind its
upstream unless you pass `--force`. On macOS a missed run happens when the Mac wakes; launchd
does not wake it. The hour is the machine's own clock. What it picks each day and why:
[Automate it](../make/automate.md#bare-metal-auto-install).

If you keep `immich-memories ui` running as a service instead, the built-in timer Docker uses works
here too (`advanced.automation.enabled: true`, `daily_at`): pick one, not both. Either way the film
stays in the output folder unless `upload.enabled` or `advanced.automation.upload_to_immich` is on:
[Upload back to Immich](./config-file.md#upload-back-to-immich).

## What to keep

`~/.immich-memories/store.db` is the file that costs a re-read to lose: banked facts, your
decisions, people and run history. `immich-memories store backup` copies it, live, to
`~/.immich-memories/backups/`; `IMMICH_MEMORIES_DATABASE_URL` moves the store to PostgreSQL, and
then `store backup` needs `pg_dump` on your `PATH`: [Database and the store](./database.md).
`~/.immich-memories/cache/` is the part you can delete: [Caches](./maintenance/health-logs-cache.md#caches).

## Logs, health and hardware

Logs go to the terminal (stderr); `-v` or `--log-level` go before the subcommand, and the daily
job's own output is kept per attempt: [Health, logs and caches](./maintenance/health-logs-cache.md).
`/health/ready` answers on the UI's port.

`immich-memories hardware` prints the encoder it found. A Mac needs nothing: VideoToolbox and Metal
are there ([Apple Silicon](./hardware.md#apple-silicon)). On Linux, install the VA-API driver or the
NVIDIA driver on the host: [Hardware encoding](./hardware.md).

## Add-ons

The same services as in Docker, each pointed at by URL in `config.yaml`:
[a reader](../better/reader.md), [captions](../better/captions.md),
[the inference service](../better/inference.md), [a render worker](../better/gpu-render.md) and
[generated music](../better/music.md).

## Updating

```bash
uv tool upgrade immich-memories
immich-memories models fetch       # a no-op unless a release moved a pin
```

With pip, keep the extra (`pip install --upgrade "immich-memories[all]"`). Going back to a release:
[Rollback](./maintenance/upgrading.md#rollback).
