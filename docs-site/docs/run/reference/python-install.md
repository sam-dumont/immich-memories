---
title: "Python installation details"
---

# Python installation details

## Extras

| Extra | What it adds |
|---|---|
| `editorial` | ONNX Runtime and Hugging Face Hub, for the context heads and the two detectors. The one you need |
| `editorial-cuda` | The same on a CUDA host. **Replaces** `editorial`, never joins it |
| `mac` | pyobjc bindings (Quartz, Metal, Vision) for hardware probing. Not enough to cut with alone |
| `music` | The bundled royalty-free track library |
| `auth` | OIDC login (authlib) |
| `demucs` | Local Demucs stem separation for music ducking (Torch, about 80 MB of model) |
| `all` | All of the above except `mac` and `editorial-cuda` |
| `all-mac` | `editorial`, `mac`, `music` and `demucs`. No `auth`: add `[all-mac,auth]` for OIDC |

Never install `editorial` and `editorial-cuda` together: `onnxruntime` and `onnxruntime-gpu` own
the same import name, and the one that answers is whichever pip wrote last.

GPU title rendering needs no extra: its kernel library is a base dependency wherever it publishes a
wheel ([Title kernels](.././hardware.md#title-kernels)). Local ACE-Step music on a Mac is a checkout
job (`make install-acestep`, then `make check-local-audio`): [Generated music](../../better/music.md).

exiftool is worth having on an Apple HEIC library: it is the fallback when the Python HDR headroom
parser trips on an unusual file. `brew install exiftool`, or `apt install libimage-exiftool-perl`.


## From a checkout

```bash
git clone https://github.com/sam-dumont/immich-video-memory-generator.git
cd immich-video-memory-generator
uv sync --extra editorial      # or --extra all-mac on Apple Silicon
make web-client                # the web UI, built from web/; needs Node 22
uv run immich-memories ui
```

`uv sync` installs into the clone's `.venv` and puts nothing on your `PATH`: inside the clone it is
always `uv run immich-memories ...`. `pip install -e ".[editorial]"` works too. A checkout is the only install
that needs Node: the PyPI wheel and the Docker image ship the web client already built. Skip
`make web-client` and the CLI still works, but `/app` only tells you to build the client.
