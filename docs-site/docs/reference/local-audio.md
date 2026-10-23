---
title: Generated audio runtime
---

# Generated audio runtime

[Generate music](../better/music.md) covers the backend choices and the local install. This page has the memory budgets, the runtime repairs and what the app does with a generated track.

## Memory and disk

`model_variant: auto`, the default, generates with the 4B XL turbo model on a Mac with 64 GB or
more of unified memory or an NVIDIA GPU with 16 GB or more (the check is 15.5 GiB, since a 16 GB
card reports a little less). XL sounds brighter and loops less. A smaller host doesn't fall back
to the 2B model: the film plays a library track (your [music folder](../make/titles-maps-music.md#your-own-music-folder)
for the moods it has, the bundled library otherwise). The same happens when XL fails to load or
doesn't fit in the memory free at that moment. A variant you write yourself is used as written:
`xl-turbo` loads XL, while `turbo` and `base` load the 2B model and log a warning.

`lib` mode checks free memory against the weights the profile has to keep resident, and refuses
with a named shortfall instead of letting macOS kill the process mid-render. A refusal counts as
a failed generation: MusicGen is tried next if enabled, then a library track.

On Linux, the budget follows the process's container limit and any tighter parent limit, capped
by the host's available memory. Clean, inactive, unmapped file cache can be reclaimed; live
allocations and shared, mapped, dirty or pinned pages remain occupied.

| Profile | Resident weights it needs free | On disk |
|---|---|---|
| XL (4B) with the 4B planner | about 29 GB | about 28 GB |
| XL (4B), `use_lm: false` | about 21 GB | about 20 GB |
| 2B with the 1.7B planner | about 11 GB | about 9 GB |
| 2B with the 0.6B planner | about 9 GB | about 7 GB |
| 2B, `use_lm: false` | about 7 GB | about 6 GB |

`immich-memories capabilities --test-music` generates 15 seconds with each local profile whose
weights fit the memory free now, the 2B ones included (films only use those when you set
`turbo` or `base`). The 0.6B and 1.7B names are the planner; the audio model is still 2B. It
reports a memory refusal separately from a failed generation. A reader loaded in oMLX holds
unified memory while idle, so unload it first if you want to test with that memory free.

The [app-owned reader](../better/reader.md) stops its model process after selection, before
local music or stem separation, and the app closes its Laya model and clears unused model
buffers; later text work starts the reader again. An external reader needs its own unload
policy. On Apple Silicon's turbo path, inactive Torch weights are parked before diffusion and the
native decoder is released before VAE decoding.

```bash
immich-memories capabilities --verify-local
```

This runs the configured owned reader and local audio on synthetic inputs with the installed
weights. It is a smoke check, not every track length or a full film. `--test-music` may download
weights; `--verify-local` never does.

Per file, under `~/.cache/ace-step/checkpoints/`: the 2B models about 4.5 GB each, XL-turbo about
19 GB, the planners 1.2, 3.4 and 7.8 GB (0.6B, 1.7B, 4B), the shared VAE and embedding about
1.4 GB. Demucs' htdemucs is about 80 MB under `~/.cache/torch/hub/`. Old checkpoints are never
removed for you.

The budgets cover weights, not peak memory: generation also allocates working buffers. The MLX
buffer cache is off on Macs with 16 GiB of RAM or less and capped at 4 GiB on larger ones. The
DiT runs in bf16; `IMMICH_MEMORIES_ACESTEP_MLX_DIT_FP32=1` switches it to fp32, which uses more
memory.

## Local runtime and repairs

`make install-acestep` installs ACE-Step v0.1.8 and Demucs into a sibling `.venv-acestep`, because
ACE-Step's Transformers pin wants an older Hugging Face library than the editor. `make
check-local-audio` generates 15 seconds, splits all four stems and fails loudly if any of it didn't
happen locally, so a remote server or a bundled track can't pass it. By default it uses the 2B
model with its 0.6B planner (about 9 GB of resident weights, 7 GB on disk), which proves the
stack works but is not the model films use; `make check-local-audio AUDIO_CHECK_ARGS="--quality high"`
checks XL with its 4B planner. Every clone and every git worktree needs its own install, since
the environment sits next to the checkout. Rerun the installer after moving the checkout or
changing the app version; it also repairs `operator torchvision::nms does not exist`. A bare
`uv sync` can remove Demucs from the editor's environment, and the installer puts it back.

The isolated stack uses PyTorch 2.13, TorchAudio 2.11 and TorchVision 0.28, with CUDA 12.6
wheels on Linux. NVIDIA driver **560.35.05 or newer** is the recommended baseline for that
series ([NVIDIA driver table](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-toolkit-release-notes/index.html#cuda-driver)).
CUDA 12 minor compatibility allows older drivers from 525.60.13 with feature and PTX/JIT
limits, and not every audio kernel is guaranteed to work there. The CUDA inference container
uses 12.8.1 and has a newer [recommended driver](./inference-service.md#running-it-with-compose).
The Mac wheels need macOS 14 or newer. The stack overrides ACE-Step v0.1.8's older Linux pins, so
its upstream metadata still reports that mismatch.

The app's own audio process turns off PyTorch's native JIT kernels before PyTorch loads, so no
compiler is needed. A library process you start yourself needs `TORCH_DISABLE_NATIVE_JIT=1` set
before Python starts; after importing PyTorch is too late.

Local CUDA generation defaults to `advanced.ace_step.cpu_offload: true`: inactive models move
back to the CPU between phases to save VRAM. Set `false` only when the card can keep them all.
API mode and Apple Silicon ignore it. Before picking CUDA for ACE-Step or Demucs, the app checks
that a CUDA kernel actually runs; a GPU the installed PyTorch can't use falls back to CPU.

### In a container

On an NVIDIA box, run ACE-Step as its own container and point the app at it with `mode: api`
and `api_url`; keep its model cache on a volume. On a Mac a container can't reach Metal, so run
ACE-Step natively and point the app in Docker at `http://host.docker.internal:8000`.

In API mode the server picks the model. The app reads `/health` and generates only when the
server reports an XL model; a 2B server, or one that doesn't say, gets a library track, and the
reason shows in the run warnings, preflight and `capabilities`. If your server runs XL without
reporting it, set `model_variant: xl-turbo`.

The app rides out a server that goes quiet for a moment. If the server restarts mid-task and
loses the task (three polls in a row with no progress, or `/v1/stats` showing it idle three
times while the task still reads as queued), the app submits it once more; a second loss falls
back to a library track at once instead of waiting out `timeout_seconds`.

When the film renders on a [render worker](./output-rendering.md) and every enabled music server
runs on a different host from that worker, the music is generated while the worker renders,
for the film the app expects back. On a shared host, in `lib` mode or with a local render, music
waits for the film.

Use this image, which frees a shared card's VRAM after an out-of-memory error:

```text
ghcr.io/sam-dumont/ace-step-1.5@sha256:45530623b81fa48fd8e4c8398d7d4df4c4ff8b16931edfc3c5cf903dee6dfc24
```

## MusicGen

Meta's MusicGen, through a remote server only: text-to-music, and Demucs stem separation on its
`/separate` endpoint. With ACE-Step enabled it is the fallback; alone, it generates.

```yaml
advanced:
  musicgen:
    enabled: true
    base_url: "http://musicgen-server:8000"
    timeout_seconds: 10800
```

Generated audio is decoded before mastering or stem separation. An empty, unreadable,
non-finite (NaN/Inf) or silent track (peak at or below -80 dBFS) counts as a failed generation.
The next enabled generator is tried; if all fail, the film plays a library track and the run
says so.

## What generation adds to the mix

- **A style per mood.** Each mood samples from the styles kept in at least 4 of 10 takes in
  listening tests, weighted by how often they were kept: solo piano, lo-fi, downtempo, neo-soul,
  post-rock, funk and city pop, depending on the mood. The other styles are never picked
  automatically.

- **Tempo fits the photos.** In a film with photos, the tempo is nudged so a photo lasts a whole
  number of beats, within the genre's range and 15 % of the mood's tempo. Videos are never
  re-timed.
- **One version, scored but never redone.** Each film's music is generated once. The take is
  scored for a metronomic, repetitive grid and the score goes to the log, but a high score never
  triggers another generation: the same check flags some bundled tracks picked by ear.
- **One film, one piece of music.** One generator makes the whole soundtrack, planned from the
  assembled film's length, so a 100 s photo film gets about 100 s of music. Every take is sent the
  mood's key, a 4/4 meter and the tempo as its own field rather than in the caption. Up to 90 s
  that is one take. A longer film gets up to 3 takes of at most 90 s that share one caption,
  style, tempo, key, time signature and seed, cut on bar lines, joined with a 0.3 s crossfade and
  matched in level, then repeated if the film is longer than 270 s. Each take ends a few seconds
  early, before its outro, and the next starts on its first downbeat.
- **Four stems.** The track is split with Demucs: vocals duck most under the clips' sound, drums
  keep their rhythm. Local Demucs uses Metal on Apple Silicon (`immich-memories[demucs]` alone).
  An enabled MusicGen server's `/separate` comes first, then the
  [inference service](inference-service.md#music-stems) when one is configured, with local
  fallback per `advanced.inference.fallback_to_local`.
