---
title: Troubleshooting
---

# Troubleshooting

**Help, in four steps:** read the table below and the [FAQ](./faq.md); check the
[release notes](https://github.com/sam-dumont/immich-video-memory-generator/releases) for your version;
[search the issues](https://github.com/sam-dumont/immich-video-memory-generator/issues?q=is%3Aissue); then open
one with the output of `immich-memories report`. It defaults to the latest run, including failed runs.
Pass a full run ID to report an older one; `report` does not resolve ID prefixes. Review the report before pasting it.

Start with the connection check and preflight:

```bash
immich-memories config test
immich-memories preflight
immich-memories report --bundle report.zip
```

In Docker, prefix the command with `docker compose exec immich-memories`. The report is redacted and nothing is sent automatically. Review it before attaching it to an issue. [Report details](../make/cli/report.md).

## When it stops

| What you see | What to do |
|---|---|
| `public heads need the pinned DINOv2 ONNX export at …` | Run `immich-memories models fetch` once. It puts the encoder and required tier artifacts on the models volume |
| `nsfw_marqo has no model: …` or `doc_docling has no model: …` | Run `models fetch` with the same tier/config as the failed run, or explicitly use `models fetch --detectors` |
| `Output directory is not writable` | In Docker the container runs as uid 1000: `mkdir output` before `up`, or `sudo chown 1000:1000 output` |
| `Story-first selection needs prepared annotations in the store at …` | The store this run opened has no prepared facts for these pictures: check the store named by `database.url` or the environment. Both `IMMICH_MEMORIES_DATABASE__URL` and `IMMICH_MEMORIES_DATABASE_URL` work. If the store is correct, run `prepare` |
| `tier: full needs an enabled LLM …` | Enable `advanced.llm.enabled`. For a native install, leave `base_url` empty for the owned local model and install its weights/server. Docker and Kubernetes need an external reader endpoint; `tier: gpu` uses the rules reader |
| `Waiting for the reader at host:port` | A configured model server stopped answering. This is a message prefix; retry details follow. See [below](#waiting-for-a-model-server) |
| `caption endpoint must advertise smolvlm2-500m-base-public` | Right weights, wrong name: alias it. See [Add captions](../better/captions.md) |
| `caption endpoint failed the compact-v3 schema control` | The server ignores the JSON schema, or it is the wrong model |
| Settings: `Secrets cannot be saved here until IMMICH_MEMORIES_SECRET_KEY is set` | Nothing is broken: keys in `.env` or `config.yaml` work without it. To save them from the page, set the key ([The secret key](../run/environment-variables.md#the-secret-key)) |
| `IMMICH_MEMORIES_SECRET_KEY must be at least 32 characters` | Use `openssl rand -base64 32`, which prints 44 |
| `This server does not answer to the host '…'` (HTTP 421) | The requested hostname is not admitted. Add the intended name to `server.allowed_hosts` and check your public URL. See [Allowed hosts](../run/network-security.md#allowed-hosts) |
| `A write from another site is refused` (HTTP 403) | A browser sent the request from another origin. Open the app at its own address; a script or cron sends no `Origin` and passes |
| `Immich account 'partner' could not read asset …` | A `generate --accounts` run stops rather than lose that account's pictures. Run `immich-memories config test`: the account's key is wrong, revoked, or lacks the asset read permissions |

## Cannot connect to Immich

The read-only check comes first: authentication and the resolved API contract, nothing searched, generated or
uploaded.

```bash
immich-memories config test
```

It prints one line and exits 1 on failure. `URL not configured` and `API key not configured` mean the setting
never reached the process.

- The URL needs its protocol (`https://`). A trailing slash is tidied up.
- A `403 Forbidden` means the key lacks rights. The scopes are on the [Docker page](../run/docker.md).
- Immich must be v2 or v3. Immich 1.x is refused at connect time.
- In Docker, `localhost` is the container. Use the host's IP or the Docker network name.

## Immich v2/v3 version mismatch

```yaml
immich:
  api_version: auto  # auto | v2 | v3
```

`auto` detects the server major at runtime; you do not pick one for each run. So a v2-to-v3 upgrade needs no
change here. If a reverse proxy hides or rewrites `/api/server/version`, use `v2` or `v3` as a manual
troubleshooting escape hatch. The override forces that contract, so go back to `auto` once detection works.

The read-only `immich-memories config test` reports the server version and authentication errors; it does not
test uploads. If a v3 upload fails, keep the error shown by the command doing the upload and check the relevant
Immich server logs. API keys are redacted.

## No videos found

- The person name must match Immich's exactly, case aside. `immich-memories people` lists them.
- Photos are in the pool by default (`photos.enabled: true`); with photos off, the period needs at least one
  video.
- A `--person` filter needs pictures where Immich recognised that face in the period.

## A picture I expected is not in the cut

```bash
immich-memories runs why <asset id> --run <run id>
```

says where it passed and where it was dropped, and why. To overrule it, tick it on the web UI's pool and
**Preview with these choices** to save a revision. Those final edits bypass the automatic sharing and length checks. For a new cut, `--include <asset id>` still passes the sharing gate. Neither can render a picture whose preview Immich answers HTTP 404 for. The run logs those as
`preview unavailable at Immich (HTTP 404)` and cuts the rest; regenerate that asset's thumbnails in Immich and
cut again. Every lever is on [Edit the cut](../how-it-chooses/overrule-it.md).

## The first cut is slow

A cut prepares the pictures it can reach once (previews, pixel facts, heads, detectors, and on the `gpu` and
`full` tiers a caption for the pictures it selects and their candidates) and banks them. The second cut over the same period is mostly the render. The levers, in order:
keep the cache volume, prepare ahead with [`prepare`](../make/cli/prepare.md) overnight, and move the heads to a
faster box with [the inference service](../better/inference.md). `immich-memories runs show` prints where
a run spent its time, and `immich-memories report` puts the same phase table in a shareable report.

During preparation, the CLI and saved progress advance by batches of new work, even when a detector ends
with a partial batch. Stage changes, counter resets and completion appear immediately.

## Waiting for a model server

When a model reader is in use, normally on the `full` tier. The run names the endpoint and tries three times, two then
four seconds apart, then stops with a message starting `Gave up on the reader at host:port`, followed by `after 3 dropped connections: fix the server and cut again`. With an explicit
`advanced.llm.base_url`, start that server or fix its URL. On a native install with an empty URL, check the configured
`local_server`, model/projector files and available memory; the app starts its own server. Docker and Kubernetes require an external endpoint: [Reader setup](../better/reader.md). Then
**Cut again** or rerun: everything already read is banked. To cut without it, set
`tier: gpu` (or `nas`): selection then uses the rules reader.

## `QuickTime cannot hold: re-encoding this clip instead of copying it`

The source is VP9 or AV1 inside a QuickTime `.MOV` (Android phones and some editors write those), and a lossless
stream copy into `.mov` would fail. The app detects that before copying and logs this message. Nothing to do: it re-encodes the clip with the same in and out points.
If a selected clip cannot be prepared, the certified render refuses the changed or incomplete content. Read the named clip failure and the report; do not treat a shorter output as the same cut.

## A long render spends a while "Checking the finished film" {#a-long-render-ends-with-ffprobe-failed-to-inspect-output-artifact}

Before a film gets its final name, FFmpeg decodes every frame once, on every core, and fails the run on any
decode error. It can take as long as the encode did, and logs
`Checking the finished film: 12:34 of 1:14:46 decoded` once a minute. That is normal on a NAS with a long film.

If it runs out of time the error reads `the decode check did not finish within the render's own encode time`
and names the file. Nothing deletes it. Check it yourself:

```bash
ffmpeg -v error -i memory.assembling.mp4 -map 0:v:0 -f null -
```

No output means every frame decoded: rename it without `.assembling` and upload it by hand (the music is
already in it).

## Out of memory

Check the failed stage and the container limit. A long film’s audio mix can exhaust a small container: the mixer runs one FFmpeg per clip
and the failure names the clip. Raise the container's memory limit.

An idle external model server can still hold gigabytes of RAM. The app-owned reader releases its process
before local ACE-Step or Demucs; an explicit API endpoint retains its own memory policy. ACE-Step in
`lib` mode refuses a profile whose weights do not fit. Check `immich-memories capabilities`; stop an
external server yourself if it is safe, or give it its own machine. Leave headroom beyond resident weights for generation and decoding; see the
[audio memory reference](local-audio.md#memory-and-disk).

## FFmpeg not found

The app calls FFmpeg by name off `PATH`, so a missing binary surfaces as
`FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'` at the first encode. `brew install ffmpeg`,
`apt install ffmpeg`, or use the Docker image.

## GPU not detected

The log says `No hardware acceleration detected, using software encoding`, and `immich-memories hardware` shows
what it sees. For NVIDIA, `nvidia-smi` must work, and Docker needs the NVIDIA Container Toolkit and the GPU
overlay. A hardware encoder only speeds up the encode. See [Hardware encoding](../run/hardware.md).

## Music generation fails

A failed generator falls back to the next one, then to a bundled track (included in Docker, or installed with the `music` extra), and the finished run says so. ACE-Step
counts as up only when `/health` returns `{"data": {"status": "ok"}}`; MusicGen needs HTTP 200. For timeouts,
raise `ace_step.timeout_seconds` (3600) or `musicgen.timeout_seconds` (10800), both capped at 18000. Setup is on
[Generated music](../better/music.md).
