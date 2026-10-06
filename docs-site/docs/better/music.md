---
title: Generate a soundtrack
---

# Generate a soundtrack

Your film already gets music: a bundled track, or an audio file you choose. A generator makes an original track for the film's mood and length. It is optional and off by default.

Without a generator, a film longer than one bundled track plays a varied, crossfaded playlist from the mood's folder instead of looping a single track, and the bundled mix is mastered to the same loudness as a generated one.

Without a generator, a film longer than one bundled track plays a varied, crossfaded playlist from the mood's folder instead of looping a single track, and the bundled mix is mastered to the same level as a generated one.

Choose the route for your machine:

| Setup | Route |
|---|---|
| Apple Silicon checkout | Local ACE-Step, in a separate audio environment. |
| Native NVIDIA checkout | Local ACE-Step, or an ACE-Step API server. |
| App container | An ACE-Step API server. |
| Existing MusicGen server | MusicGen API, also usable as an ACE-Step fallback. |

## Local on a Mac

From your checkout:

```bash
make dev-mac
make install-acestep
make check-local-audio
```

Every checkout and worktree needs its own `make install-acestep`. The audio stack lives in `.venv-acestep` next to the checkout. The check generates and separates real audio locally; a bundled fallback does not pass it.
It uses the 2B model with a 0.6B planner, requiring about **9 GB for resident weights** and
**7 GB on disk**. That test profile is larger than the planner-free configuration below.

Start with the smaller default model:

```yaml
advanced:
  ace_step:
    enabled: true
    mode: lib
    model_variant: turbo
    use_lm: false
```

The 2B profile without its planner needs about **7 GB free for resident weights** and **6 GB on disk**. An app-owned local reader releases its model memory before local music or stem separation. An external reader server owns its own memory and must leave enough free for audio. Larger profiles, supported platform versions and audio-environment repairs are in the [audio runtime reference](../reference/local-audio.md#memory-and-disk).

## Local on NVIDIA

Native Linux checkouts can use the same `lib` configuration. CUDA offload is on by default: models move back to CPU between audio phases to reduce VRAM use. Set `advanced.ace_step.cpu_offload: false` only when the GPU can keep them resident.

The setting does not affect Apple Silicon or API servers. See [runtime requirements](../reference/local-audio.md) before installing the native audio stack.

## API server

Use the upstream [ACE-Step 1.5 REST server](https://github.com/ace-step/ACE-Step-1.5/blob/v0.1.8/docs/en/API.md),
installed following its own server instructions. Its `acestep-api` entry point serves
`GET /health`, `POST /release_task`, `POST /query_result` and the returned audio download URL.
The app expects that API; a Gradio UI alone is not this server. The upstream default port is
8001; set `ACESTEP_API_PORT=8000` to use the example below. Bind a private address reachable
from the app and keep the service off the public internet. Then configure the app:

```yaml
advanced:
  ace_step:
    enabled: true
    mode: api
    api_url: http://music.example.lan:8000
```

The server owns its weights and GPU. An app in Docker Desktop can reach a native Mac server through `host.docker.internal`. A Mac container cannot use Metal.

### Sharing one GPU with the worker

Tested sharing ACE-Step with the render worker on one small GPU card: both films completed
serially, with generated music and four-stem separation. See
[Measure your setup](./measured.md#render-worker-and-music-sharing-one-gpu) for the numbers.
Use a build containing the model-loading cleanup fix (see
[pinned ACE-Step image](../reference/local-audio.md#in-a-container)). GPU Operator time-slicing
provides access to one card, not separate VRAM pools or model unloading. The combined worker
releases its own models between phases; the separate ACE-Step service must manage its own
lifetime. Run one film at a time on a shared small card. A successful `/health` response does
not prove generation fits: check an actual generated track and its stem separation.

[MusicGen configuration](../reference/local-audio.md#musicgen) uses its own server and endpoint.

## Check the result

```bash
immich-memories preflight
immich-memories music preview RUN_ID
```

Preview before rendering. If generation fails, the app tries the next enabled backend and then a bundled track. The finished run reports the substitution.

Generated music can be separated into stems for ducking under clip audio. The configured inference service, a local Demucs install or an enabled MusicGen server can do that job. [Runtime and mixing details](../reference/local-audio.md).
