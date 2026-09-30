---
title: Generate a soundtrack
---

# Generate a soundtrack

Your film already gets music: a bundled track, or an audio file you choose. A generator makes an original track for the film’s mood and length. It is optional and off by default.

Choose the route for your machine:

| Setup | Route |
|---|---|
| Apple Silicon checkout | Local ACE-Step, in a separate audio environment. |
| NVIDIA host or app container | An ACE-Step API server. |
| Existing MusicGen server | MusicGen API, also usable as an ACE-Step fallback. |

## Local on a Mac

From your checkout:

```bash
make dev-mac
make install-acestep
make check-local-audio
```

Every checkout and worktree needs its own `make install-acestep`. The audio stack lives in `.venv-acestep` next to the checkout. The check generates and separates real audio locally; a bundled fallback does not pass it.

Start with the smaller default model:

```yaml
advanced:
  ace_step:
    enabled: true
    mode: lib
    model_variant: turbo
    use_lm: false
```

The 2B profile without its planner needs about **7 GB free for resident weights** and **6 GB on disk**. A loaded reader uses memory too. Larger profiles, supported platform versions and audio-environment repairs are in the [audio runtime reference](../reference/local-audio.md#memory-and-disk).

## API server

Configure a server you already run:

```yaml
advanced:
  ace_step:
    enabled: true
    mode: api
    api_url: http://music.example.lan:8000
```

The server owns its weights and GPU. An app in Docker Desktop can reach a native Mac server through `host.docker.internal`. A Mac container cannot use Metal.

[MusicGen configuration](../reference/local-audio.md#musicgen) uses its own server and endpoint.

## Check the result

```bash
immich-memories preflight
immich-memories music preview RUN_ID
```

Preview before rendering. If generation fails, the app tries the next enabled backend and then a bundled track. The finished run reports the substitution.

Generated music can be separated into stems for ducking under clip audio. The configured inference service, a local Demucs install or an enabled MusicGen server can do that job. [Runtime and mixing details](../reference/local-audio.md).
