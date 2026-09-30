---
title: On a NAS
---

# On a NAS

The NAS that runs Immich runs this too, on its own, and makes the whole film there. A GPU or a
model makes it better later ([what each one adds](../get-started/what-a-gpu-or-a-model-adds.md)).
The install is the
[Docker Compose](./docker.md) one; this page is what is different on a Synology, QNAP, TrueNAS or
Unraid box. It has run on a Synology DS423+ (Celeron J4125, four cores); when, and on which release:
[Supported and tested](./requirements.md#supported-and-tested).

## Install

Synology Container Manager, QNAP Container Station, TrueNAS SCALE Apps and the Unraid Docker
Compose Manager plugin all take the compose file as a project. Put `docker-compose.yml` and your
`.env` (from `example.env`) in the project folder, create an `output` folder beside them, and
start the project. Then, from an SSH session in that folder:

```bash
sudo docker compose exec immich-memories immich-memories models fetch
sudo docker compose exec immich-memories immich-memories preflight
```

The compose file uses `tier: auto`, which picks the `nas` tier here: the eight context heads share
one DINO encoder on the NAS CPU, and no caption or model service is needed.

Set the home base in `.env` before the first cut
(`IMMICH_MEMORIES_TRIPS__HOMEBASE_LATITUDE` and `..._LONGITUDE`). It also picks your country's public
holidays. Without it no day counts as
away from home, so a three-week holiday arrives as three weekly stories instead of one trip. Then
confirm who's who once: [Teach it your family](../get-started/who-is-who.md).

After `models fetch` and a clean `preflight`, start with one month:

```bash
sudo docker compose exec immich-memories immich-memories generate --year 2025 --month 8
```

The first cut includes fresh preparation. The [measured preparation times](../better/measured.md#nas-preparation)
exclude downloads, music and rendering; they are not a promise for the whole film.

### The output folder

The container runs as UID 1000. On Synology the folder a DSM user creates belongs to that user,
usually not 1000, and the first cut refuses with `Output directory is not writable`. Either
`sudo chown -R 1000:1000 output` over SSH, or set `user: "<your uid>:<your gid>"` on the service
(`id` prints them) and chown the config volume to match. If neither suits, drop the `./output`
mount and turn on upload-back: the film goes to Immich instead.

### Do not use `cpus:` on a Synology

`cpus:` is a CFS quota, and DSM runs a cgroup v1 kernel built without the CFS bandwidth
controller. A DS423+ answers `docker compose up` with `NanoCPUs can not be set, as your kernel
does not support CPU CFS scheduler or the cgroup is not mounted` and starts nothing. The shipped
file sets no CPU limit for that reason. To keep cores free for Immich, pin them instead:

```yaml
    cpuset: "0-2"      # three of four cores; works without CFS
```

Memory limits work on every NAS tested.

### Reaching the UI

The UI is on the NAS's loopback only. From your desktop:

```bash
ssh -L 8080:localhost:8080 you@your-nas
```

then open `http://localhost:8080`. To put it on the LAN instead, turn on
[authentication](./authentication.mdx) first, then change the mapping to `"8080:8080"`. UniFi and
other NAS apps often hold 8080 already: change the left side (`127.0.0.1:8081:8080`) and tunnel
to that port.

## What to expect

The first cut of a month reads every picture it can reach once and banks the answers in the
persistent store. The eight context heads share one DINO encoder. NAS disables Docling and Marqo;
GPU and Full enable both, using a configured [inference service](../better/inference.md) when
available. The `screen`, `frame_kind` and `uncovered_person` heads still run on NAS. This saves
work but gives up detector coverage; it is not proven equivalent to GPU or Full. Run it in the
evening. Later cuts reuse matching facts; new pictures and changed producers
can require more work. `immich-memories runs show` prints where the time went, phase by phase and
per picture. A 162-image test on the DS423+ took 112 seconds for fresh DINO-only classifier preparation.
Warm preparation made no model calls. Downloads, captions and rendering are separate costs; see
[the preparation measurements](../better/measured.md#nas-preparation).

Start with one month, not a year: preparation grows with the pictures in the window, not with the
length of the film. To read a bigger window ahead of time, run
`immich-memories prepare --year 2025` overnight; later cuts inside it start warm.

## Encoding

The default codec is H.264, which Intel Quick Sync encodes in hardware. Pass the render node
through to use it; the compose file carries the block commented out:

```yaml
    devices:
      - /dev/dri:/dev/dri
    group_add:
      - "937"          # the GID that owns /dev/dri/renderD128 on DSM
```

`stat -c '%g' /dev/dri/renderD128` on the host prints the GID. Without `group_add` the device is
there and the container cannot open it. More on [Hardware encoding](./hardware.md#intel-quick-sync-and-amd-vaapi).

With `output.codec: h265`, remember that Gemini Lake (the J4125 class) has no HEVC encode:
that part goes to software, and the log says `vaapi cannot encode h265 on this device`. ARM NAS
models have no hardware encoder here at all.

The J4125 has no AVX either, so the CPU fallback draws the titles instead of the animated
kernels: [CPUs without AVX](./hardware.md#cpus-without-avx).

## Long films

A long album on two cores is a long encode, and after the music is mixed in the app decodes the
whole film once to prove it plays. That check can take as long again as a 1080p encode, logs
`Checking the finished film: ... decoded` once a minute, and a film that fails it stays on disk:
[Troubleshooting](../reference/troubleshooting.md#a-long-render-ends-with-ffprobe-failed-to-inspect-output-artifact).
Keep 4K for a box with more cores, or send the render to a
[GPU box](../better/gpu-render.md).

## Memory and disk

The 4 GB limit in the compose file is what the tested runs used. The render blends one clip at a
time, so its memory does not grow with the number of clips.

Size `cache.thumbnail_cache_max_size_mb` against your library: too small and the next overlapping
memory downloads every preview again, which on a NAS is the slow part. The budget per picture is in
the [config reference](../reference/config-reference.md#size-the-thumbnail-cache-by-your-library).
Selection reads those previews from disk as needed. It retains the per-picture availability result,
not every JPEG in RAM, so a large cached person or trip scope does not need its entire preview cache
in memory. Cached detector facts still avoid model inference.

A NAS volume is usually the smallest disk in the setup, and often shared with everything else on
the box. A run that uploads to Immich has its local film removed as soon as the upload is
confirmed, so nightly automation does not grow `output.directory` on its own. A run kept local
(`upload_enabled: false`, or a delivery that stays pending) does not clean up on its own: watch it
with `immich-memories runs storage` and clear it with `runs delete`. Below
`output.min_free_space_gb` (5 GB by default) on the output or cache volume, a run warns; if a film
would not fit at all, the run stops before rendering rather than filling the volume mid-encode.
See [health, logs and caches](./maintenance/health-logs-cache.md#caches).

## What a NAS can't do

- Run GPU selection without GPU inference. A render-only GPU does not count. A configured LLM
  alone leaves selection on NAS, while still supplying titles and music mood:
  [Add a reader](../better/reader.md).
- Caption quickly on a small CPU. Use a GPU caption service for the selected shots and actual
  candidates. Captioning a whole library is a separate `prepare` job. An LLM can supply captions
  only with explicit opt-in, which is less efficient and can cost much more on hosted services:
  [Add captions](../better/captions.md).
- Generate music: MusicGen and ACE-Step want a GPU. The bundled tracks and your own uploads work.

## Every night

Uncomment `IMMICH_MEMORIES_AUTOMATION__ENABLED` and `IMMICH_MEMORIES_AUTOMATION__DAILY_AT` in the
compose file and set `TZ` in `.env`. The UI process makes one memory a day by itself; there is no
cron to install. [Daily automation](./docker.md#daily-automation), which also says how the daily
film reaches Immich.

## Everything else

Same container, same commands, prefixed with `sudo` over SSH on most NAS systems. On the Docker page:
[the API key](./docker.md#the-api-key), [films into Immich](./docker.md#films-into-immich),
[logs and health](./docker.md#health-check-and-logs), [backups and the store](./docker.md#what-to-keep),
[updating](./docker.md#updating), [hardening](./docker.md#hardening) and the
[add-ons](./docker.md#add-ons-as-profiles).
