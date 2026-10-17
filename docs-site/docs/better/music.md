---
title: Generate a soundtrack
---

# Generate a soundtrack

Your film already gets music: a bundled track, or an audio file you choose. A generator makes an original track for the film's mood and length. It is optional and off by default.

The music reads the season in your home base's hemisphere, the same way titles do (set the home base in Settings, or `trips.homebase_latitude`). The mood follows what the film is. A birthday or a trip gets a lively mood, an ordinary month moves with how many of its shots play, and a quiet month of still photos gets calm. A text reader can choose it from the cut's text; without one, the film's own facts do. [How the music is picked](../reference/output-rendering.md#music) has the table.

The generator picks a style from the film's mood, and the pick follows what was kept in listening tests on real films. Each mood has its own short list: calm leans on solo piano, downtempo and neo-soul; tender on neo-soul and solo piano; nostalgic on post-rock, neo-soul, lo-fi and piano; happy on city pop, lo-fi, electronic and piano; energetic on funk, post-rock, lo-fi and piano. A style that was kept in fewer than four takes out of ten for a mood is left out of that mood. Acoustic folk, jazz trio, indie rock, orchestral, ambient and metal exist in the caption matrix but the app never picks them by itself.

A generated soundtrack plays as one piece. With ACE-Step, a film up to 30 seconds gets a single take; a longer one joins short takes that share one style, tempo and key, on a bar line. Every take gets a key and a 4/4 meter chosen with the mood, because ACE-Step left to guess did worse in every style.

Without a generator, a film plays one bundled track, looped onto itself where its own music repeats, so it never jumps to a different piece. The bundled mix is mastered to the same loudness as a generated one.

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

Then turn it on:

```yaml
advanced:
  ace_step:
    enabled: true
    mode: lib
    use_lm: false
```

The model is picked from the machine: the 4B XL model on a Mac with 64 GB or more of unified memory, the 2B model below that. XL sounds brighter; if it doesn't fit when the render starts, the render uses 2B and says so in the log. Set `model_variant: turbo` to always use 2B, or `xl-turbo` to always use XL.

The 2B profile without its planner needs about **7 GB free for resident weights** and **6 GB on disk**; XL needs about **21 GB** and **20 GB**. An app-owned local reader releases its model memory before local music or stem separation. An external reader server owns its own memory and must leave enough free for audio. Larger profiles, supported platform versions and audio-environment repairs are in the [audio runtime reference](../reference/local-audio.md#memory-and-disk).

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

The server owns its weights and GPU, so it picks the model: `model_variant` only applies to `lib` mode. The app asks the server not to run its 5Hz planner (`thinking`, `use_cot_caption` and `use_cot_metas` all false), because a server with a planner loaded would otherwise rewrite the app's caption before generating. Set `use_lm: true` to let it. Mastering stays in the app either way.

An app in Docker Desktop can reach a native Mac server through `host.docker.internal`. A Mac container cannot use Metal.

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

In Docker, prefix `immich-memories` commands with `docker compose exec immich-memories`
from the app's installation folder.

```bash
immich-memories preflight
immich-memories music preview RUN_ID
```

Preview before rendering. If generation fails, the app tries the next enabled backend and then a bundled track. The finished run reports the substitution.

Generated music can be separated into stems for ducking under clip audio. The configured inference service, a local Demucs install or an enabled MusicGen server can do that job. [Runtime and mixing details](../reference/local-audio.md).
