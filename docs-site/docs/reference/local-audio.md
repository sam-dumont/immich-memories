---
title: Generated audio runtime
---

# Generated audio runtime

Start with [Generate music](../better/music.md) for the supported backend choices and local installation. This reference covers model budgets, runtime repairs and generated-track handling.

## Memory and disk

`lib` mode checks free memory against the weights the profile has to keep resident, and refuses
with a named shortfall rather than letting macOS kill the process mid-render. A refusal is an
ordinary backend failure: MusicGen is next, then a bundled track.

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

Check this machine with `immich-memories capabilities --test-music`. It tries the configured
profile and the smaller 2B profiles when their weight budgets fit the memory available now.
The 0.6B name refers to the planner; the audio generator is still 2B. A reader that stays loaded
in oMLX still uses unified memory while idle. Unloading it can make a smaller music profile fit;
the command reports a refusal separately from a generation failure.

The [app-owned reader](../better/reader.md) releases its model process after selection, before titles and rendering, and before local music or stem separation. The app also closes its selection-owned Laya model and clears unused local model buffers. Later text work can reopen the owned reader, so the stages can use the same memory at different times. An external reader needs its own unload policy. On Apple Silicon's turbo path, inactive Torch weights are parked before native diffusion; the native decoder is released before VAE decoding.

```bash
immich-memories capabilities --verify-local
```

This checks the configured owned reader and local audio with installed weights and synthetic inputs. A verified result covers that smoke check, not every track length or a full film. Use `--test-music` instead to try fitting smaller profiles; it may download their weights.

Per file, under `~/.cache/ace-step/checkpoints/`: the 2B models about 4.5 GB each, XL-turbo about
19 GB, the planners 1.2, 3.4 and 7.8 GB (0.6B, 1.7B, 4B), the shared VAE and embedding about
1.4 GB. Demucs' htdemucs is about 80 MB under `~/.cache/torch/hub/`. Old checkpoints are never
removed for you.

Weight budgets are not peak-memory guarantees: generation also allocates working buffers. The MLX buffer cache is disabled on Macs with at most 16 GiB physical RAM and capped at 4 GiB on larger Macs. The DiT uses bf16 by default; `IMMICH_MEMORIES_ACESTEP_MLX_DIT_FP32=1` selects fp32 and increases its memory use. An external reader can keep memory occupied while idle; unload it through that server’s controls when local music cannot fit.

## Local runtime and repairs

`make install-acestep` installs ACE-Step v0.1.8 and Demucs into a sibling `.venv-acestep`, because
ACE-Step's Transformers pin wants an older Hugging Face library than the editor. `make
check-local-audio` generates 15 seconds, splits all four stems and fails loudly if any of it didn't
happen locally, so a remote server or a bundled track can't pass it. Every clone and every
git worktree needs its own run, since the environment sits next to the checkout. Rerun the
installer after moving the checkout or changing the app version; it also repairs
`operator torchvision::nms does not exist`. A bare `uv sync` can remove Demucs from the editor's
environment, and the installer puts it back.

The isolated stack uses patched PyTorch 2.13, TorchAudio 2.11's stable ABI, and TorchVision 0.28;
Linux uses the CUDA 12.6 wheels, and the Mac wheels require macOS 14 or newer. This tested stack
overrides ACE-Step v0.1.8's older Linux package pins, so its upstream dependency metadata still
reports that mismatch. The app disables PyTorch native JIT kernels in its own audio child before
PyTorch imports, keeping the existing eager path free of a compiler requirement. A custom direct
library process needs `TORCH_DISABLE_NATIVE_JIT=1` before Python starts; setting it after importing
PyTorch is too late. Local CUDA generation defaults to `advanced.ace_step.cpu_offload: true`: inactive models move back to CPU between phases to reduce VRAM use. Set it to `false` only when the card has room to keep them resident. API mode and Apple Silicon ignore this CUDA setting; the host and container memory guard still applies.

Automatic local ACE-Step and Demucs selection checks that a CUDA kernel actually runs and synchronizes. A detected GPU whose installed PyTorch build cannot execute it falls back to CPU. ACE-Step still checks available memory before loading weights.

### In a container

A separate ACE-Step container serves the editor with `mode: api` and `api_url` pointing at it; keep
its model cache on a volume. On an NVIDIA box that is the way to go. On a Mac, a container can't
reach Metal, so run ACE-Step natively and point the app in Docker at
`http://host.docker.internal:8000`.

## MusicGen

Meta's MusicGen, through a remote server only: text-to-music, and Demucs stem separation on its
`/separate` endpoint. With ACE-Step enabled it is the fallback; alone, it generates.

```yaml
advanced:
  musicgen:
    enabled: true
    base_url: "http://musicgen-server:8000"
    timeout_seconds: 10800
    num_versions: 3
```

Generated audio is decoded before mastering or stem separation. Empty, unreadable, non-finite
(NaN/Inf), and silent tracks (peak at or below -80 dBFS) count as failed generations. The next
enabled generator is tried; if all fail, automatic music uses the bundled library and reports
the substitution.

## What generation adds to the mix

- **Tempo fits the photos.** In a film with photos, the tempo is nudged so a photo lasts a whole
  number of beats, within the genre's range and 15 % of the mood's tempo. Videos are never
  re-timed.
- **A stuck loop is re-rolled.** Each take is checked for a metronomic, repetitive grid, and a
  flagged one is replaced by up to `audio.max_regenerations` (2) more takes, keeping the best.
  Music is never dropped for it.
- **Long films chain takes.** Past `audio.music_block_seconds` (120), up to
  `audio.max_music_blocks` (3) distinct takes are crossfaded and looped, rather than one long
  generation. ACE-Step bounds each take to the block length while keeping all scene moods
  in its prompt, even when the scenes describe a longer film.
- **Four stems.** The track is split with Demucs: vocals duck most under the clips' sound, drums
  keep their rhythm. Local Demucs uses Metal on Apple Silicon (`immich-memories[demucs]` alone);
  the configured [inference service](inference-service.md#music-stems) handles separation over HTTP,
  with local fallback controlled by `advanced.inference.fallback_to_local`. An explicitly enabled
  MusicGen server's `/separate` keeps priority.
