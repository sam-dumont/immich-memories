---
title: Troubleshooting
---

# Troubleshooting

Still installing? Start with [Installation help](./installation-help.md). For an active or
interrupted film, see [Film progress and recovery](../run/film-progress.md).

**Help, in four steps:** read the table below and the [FAQ](./faq.md); check the
[release notes](https://github.com/sam-dumont/immich-memories/releases) for your version;
[search the issues](https://github.com/sam-dumont/immich-memories/issues?q=is%3Aissue); then open
one with the output of `immich-memories report`. It reports the latest run, failed ones included.
For an older run, pass its full run ID: `report` doesn't take prefixes.

Start with the connection check and preflight:

```bash
immich-memories config test
immich-memories preflight
immich-memories report --bundle report.zip
```

In Docker, prefix commands with `docker compose exec immich-memories`. To save the report on the
host, use the mounted output folder:

```bash
docker compose exec immich-memories immich-memories report --bundle /app/output/report.zip
```

The file is `./output/report.zip` on the host. The report is redacted and nothing is sent anywhere.
Read it before you attach it to an issue. [Report details](../make/cli/report.md).

## When it stops

| What you see | What to do |
|---|---|
| `public heads need the pinned DINOv2 ONNX export at …` | Run `immich-memories models fetch` once. It puts the encoder and the tier's other models on the models volume |
| `nsfw_marqo has no model: …` or `doc_docling has no model: …` | Run `models fetch` with the same tier and config as the failed run, or `models fetch --detectors` |
| `Output directory is not writable` | The container runs as UID 1000. Create `output` and give that user write permission; creating the folder alone is not enough. See [output permissions](../run/nas.md#the-output-folder) |
| `Output directory … is not a mounted volume` | Films written there are lost when the container is replaced. Mount a volume or a persistent claim at that path |
| `IMMICH_MEMORIES_OUTPUT__DIRECTORY=… overrides config.yaml's output.directory` | The image sets this variable, and environment variables win over the file. Unset it, or point it at the directory you mounted |
| `Story-first selection needs prepared annotations in the store at …` | The store this run opened has no prepared facts for these pictures: check the store named by `database.url` or the environment. Both `IMMICH_MEMORIES_DATABASE__URL` and `IMMICH_MEMORIES_DATABASE_URL` work. If the store is correct, run `prepare` |
| `tier: full needs an enabled LLM …` | Enable `advanced.llm.enabled`. For a native install, leave `base_url` empty for the owned local model and install its weights/server. Docker and Kubernetes need an external reader endpoint; `tier: gpu` uses the rules reader |
| `Waiting for the reader at host:port: connection dropped, retry 1 of 3`, then `Gave up on the reader at …` | A configured model server stopped answering. The film goes on with the rules. See [below](#waiting-for-a-model-server) |
| `caption endpoint must advertise smolvlm2-500m-base-public` | Right weights, wrong name: alias it. See [Add captions](../better/captions.md) |
| `caption endpoint failed the compact-v3 schema control` | A captioner that just started can take minutes to answer its first request, so the app retries that check once with more time. If it fails again, the server ignores the JSON schema, or it runs the wrong model |
| `Waiting for the inference worker (busy with another job, … s so far)` | Another run's render or music holds the worker's GPU. Captions wait, up to 25 minutes, and go on once it's free. Nothing to do |
| `the inference worker stayed busy for … minutes (another job holds its GPU)` | The other job outlasted the wait. Rerun once the worker is free |
| Settings: `Secrets cannot be saved here until IMMICH_MEMORIES_SECRET_KEY is set` | Nothing is broken: keys in `.env` or `config.yaml` work without it. To save them from the page, set the key ([The secret key](../run/environment-variables.md#the-secret-key)) |
| `IMMICH_MEMORIES_SECRET_KEY must be at least 32 characters` | Make one with `openssl rand -base64 32` (44 characters) |
| `This server does not answer to the host '…'` (HTTP 421) | The hostname isn't allowed. Add it to `server.allowed_hosts` and check your public URL. See [Allowed hosts](../run/network-security.md#allowed-hosts) |
| `A write from another site is refused` (HTTP 403) | A browser sent the request from another origin. Open the app at its own address. A script or cron job sends no `Origin` and passes |
| `Immich account 'partner' could not read asset …` | A `generate --accounts` run stops rather than lose that account's pictures. Run `immich-memories config test`: the account's key is wrong, revoked, or lacks the asset read permissions |
| `Request failed: cannot reach <host> (<Exception>)`, then `retrying (n/N)` | This process can't reach Immich. Check the host and port in the error and Immich itself; the run retries [before it gives up](#immich-briefly-stops-answering) |
| Web create page shows "Immich unreachable" | The web server's own check to Immich failed. Fix the connection ([Cannot connect to Immich](#cannot-connect-to-immich)) and reload the page |
| `Reader unreachable at <endpoint> (…); falling back to rules and default wording` | A configured text reader stopped answering. The film ships the rules draft with default wording. The warning appears once per endpoint |
| `Storage is full or its quota is exhausted` | The cache or output volume, or the database, ran out of space. Expand it, or clear disposable caches while the app is idle, then retry. Don't delete the store. See [full disk](../run/maintenance/storage-backups.md#full-disk-during-preparation) |
| `<clip> leaves the film: …` or `<clip> plays as its still: …` | A selected clip couldn't be prepared or gave no frame at assembly. A Live Photo plays as its still in the same slot; any other clip leaves and the film is that much shorter. The reason follows the colon |
| `A prepared clip disappeared before assembly (…)` | Something deleted a prepared clip while the film rendered. Render it again |
| `The render worker's film runs …s against the …s planned` | A worker film within 3% of its planned length ships with this warning. Nothing to do |
| `Render worker changed the film duration: …s against the …s planned` | The worker's film is more than 3% off the plan. Render again; if it repeats, open an issue with `immich-memories report` |
| `uploaded without description: the key lacks asset.update`, or `uploaded without story tags: the key lacks …` | The film is in Immich; only its label is missing. Add the named permission to the API key ([the API key](../run/docker.md#the-api-key)); the next upload gets it |

## I lost the generated password

The first start prints the username and password once in the server log. The app keeps only a
hash, so it cannot show them again. Make a new password: the command prints it once in the terminal
and signs every browser out.

```bash
docker compose exec immich-memories immich-memories auth reset-password
```

On a pip or uv install, run `immich-memories auth reset-password` directly. To skip the generated password for good, set your own login
([Authentication](../run/authentication.mdx)).

## Cannot connect to Immich

Run the read-only check first. It tests authentication and the API version, and searches, generates and
uploads nothing.

```bash
immich-memories config test
```

It prints one line and exits 1 on failure. `URL not configured` and `API key not configured` mean the setting
never reached the process.

- The URL needs its protocol (`https://`). A trailing slash is tidied up.
- A `403 Forbidden` means the key lacks rights. The scopes are on the [Docker page](../run/docker.md).
- Immich must be v2 or v3. Immich 1.x is refused at connect time.
- In Docker, `localhost` is the container. Use the host's IP or the Docker network name.
- On a Mac, `No route to host` or `errno 65` to an address like `192.168.x.x`, while `curl` reaches it, is the Local Network permission: it belongs to the Python the scheduled job runs, not to Terminal. `auto install` checks it at the Mac: macOS asks on the screen whether that Python may find devices on your local network, and waits there until someone answers. Click **Allow** and run `auto install` again, or turn it on in System Settings ([details](../run/reference/python-install.md#macos-and-an-immich-on-your-network)).

## Immich v2/v3 version mismatch

```yaml
immich:
  api_version: auto  # auto | v2 | v3
```

`auto` detects the server major at runtime; you do not pick one for each run. A v2-to-v3 upgrade
needs no change here. If a reverse proxy hides or rewrites `/api/server/version`, use `v2` or `v3` as a
manual troubleshooting escape hatch. The override forces that contract; go back to `auto` once
detection works.

The read-only `immich-memories config test` reports the server version and authentication errors; it
does not test uploads. If a v3 upload fails, keep the error shown by the command doing the upload and
check the relevant Immich server logs. API keys are redacted.

## No videos found

- The person name must match Immich's exactly, case aside. `immich-memories people` lists them.
- Photos are in the pool by default (`photos.enabled: true`); with photos off, the period needs at least one
  video.
- A `--person` filter needs pictures where Immich recognised that face in the period.

## A picture I expected is not in the cut

```bash
immich-memories runs why <asset id> --run <run id>
```

says where it passed and where it was dropped, and why. To overrule it, tick it in the web UI's pool and
select **Preview with these choices** to save a revision; those edits skip the automatic sharing and length
checks. For a new cut, `--include <asset id>` still goes through the sharing check. Every lever is on
[Edit the cut](../how-it-chooses/overrule-it.md).

If the log says `preview unavailable at Immich (HTTP 404)`, Immich lost that picture's preview file. The run
drops the picture and cuts the rest. Regenerate the asset's thumbnails in Immich, then cut again.

## Preflight says Immich is connected, but cuts hang on thumbnails

Small API calls pass, so preflight is green. Thumbnails need bigger packets, and they stall when the host's network MTU is below Docker's 1500, which VPNs, overlay networks, Kubernetes and some cloud VMs do. Set the Compose network MTU below the host's with a `docker-compose.override.yml` next to `docker-compose.yml`:

```yaml
networks:
  default:
    driver_opts:
      com.docker.network.driver.mtu: "1300"
```

Then `docker compose down && docker compose up -d`.

## Immich briefly stops answering

At startup, the first permission check tries once and waits five seconds for a connection. If Immich
doesn't answer, fix the connection and rerun the command.

After that, library reads and downloads try up to seven times on connection failures, timeouts, rate
limits and temporary server errors, waiting 1, 2, 4, 8, 15 and 15 seconds in between: 45 seconds, which
covers a quick Immich restart. Writes retry twice. Authentication failures and missing assets aren't
retried.

If Immich stays down, the run stops with the connection error. Fix Immich and rerun: finished
preparation stays in the cache.

## The first cut is slow

The first cut prepares previews, pixel facts and small classifier results for every picture in the period.
GPU and Full add detectors and captions for the selected pictures and their replacements. Later cuts reuse
those facts. To spend less time on it:

- keep the cache volume between runs;
- prepare ahead with [`prepare`](../make/cli/prepare.md), overnight;
- move the heads to a faster box with [the inference service](../better/inference.md).

`immich-memories runs show` prints where a run spent its time, and `immich-memories report` puts the same
table in a shareable report. Progress moves in batches during preparation, so a counter that sits still for a
moment isn't stuck.

## Waiting for a model server

`Waiting for the reader at host:port: connection dropped, retry 1 of 3` means the text model server (normally
on the `full` tier) dropped the connection. The run tries three times, two then four seconds apart, then logs
`Gave up on the reader at host:port after 3 dropped connections: check that server`. For the rest of that run
it doesn't ask the server again: the film ships the rules draft with default wording, plus any answers the
reader already gave.

To fix the server:

- with `advanced.llm.base_url` set, start that server or fix the URL;
- on a native install with an empty URL, the app starts its own server: check `local_server`, the model and
  projector files and free memory;
- Docker and Kubernetes need an external endpoint: [Reader setup](../better/reader.md).

Then **Cut again** or rerun for the reader's cut; everything it already read is kept. To stop using a reader,
set `tier: gpu` (or `basic`).

## `QuickTime cannot hold: re-encoding this clip instead of copying it`

The source is VP9 or AV1 inside a QuickTime `.MOV` (some Android phones and editors write those), which a
lossless copy into `.mov` can't hold. Nothing to do: the app re-encodes the clip with the same in and out
points. If a clip can't be prepared at all, it [leaves the film](#when-it-stops) by name.

## A long render spends a while "Checking the finished film" {#a-long-render-ends-with-ffprobe-failed-to-inspect-output-artifact}

Before a film gets its final name, FFmpeg decodes every frame once, on every core, and fails the run on any
decode error. It can take as long as the encode did, and logs `Checking the finished film: 12:34 of 1:14:46
decoded` once a minute. On a NAS with a long film, that's normal.

If it runs out of time the error reads `the decode check did not finish within the render's own encode time`
and names the file. Nothing deletes it. Check it yourself:

```bash
ffmpeg -v error -i memory.assembling.mp4 -map 0:v:0 -f null -
```

No output means every frame decoded: rename it without `.assembling` and upload it by hand (the music is
already in it).

## Out of memory

Check which stage failed and the container's memory limit. A long film's audio mix can run a small container
out of memory: the mixer runs one FFmpeg per clip, and the failure names the clip. Raise the limit.

An idle external model server can still hold gigabytes of RAM. The app's own reader stops before local
ACE-Step or Demucs start; a server you run yourself keeps its memory. ACE-Step in `lib` mode refuses a model
whose weights don't fit. Check `immich-memories capabilities`, stop the external server if that's safe, or move
it to its own machine. Generation and decoding need room beyond the weights: see the
[audio memory reference](local-audio.md#memory-and-disk).

## FFmpeg not found

`FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'` at the first encode: FFmpeg isn't on
`PATH`. Run `brew install ffmpeg` or `apt install ffmpeg`, or use the Docker image.

## GPU not detected

The log says `No hardware acceleration detected, using software encoding`. `immich-memories hardware` shows
what the app sees. For NVIDIA, `nvidia-smi` must work, and Docker needs the NVIDIA Container Toolkit and the GPU
overlay. See [Hardware encoding](../run/hardware.md).

## Music generation fails

A failed generator falls back to the next one, then to a bundled track, and the finished run says so.
The bundled library comes with `immich-memories models fetch` and is built into the Docker image; a pip or uv
install that never ran `models fetch` (and lacks the `music` extra) has no tracks to fall back on. ACE-Step
counts as up only when `/health` returns `{"data": {"status": "ok"}}`; MusicGen needs HTTP 200. On timeouts,
raise `ace_step.timeout_seconds` (default 3600) or `musicgen.timeout_seconds` (default 10800), both capped at
18000. Setup is on [Generated music](../better/music.md).

## Start over deliberately

A retry keeps the preparation a failed run finished. For a clean slate, follow
[the scoped app-state reset](../run/lifecycle.md#3-reset-app-state-for-a-fresh-trial). Back up first, and
don't delete every volume or anything Immich owns.
