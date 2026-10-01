---
title: "Diagnostics and monitoring"
---

# Diagnostics and monitoring

Start with preflight when a film fails. Health endpoints are for monitoring the running web process.

## Preflight

The endpoints answer "is the web process up". `preflight` answers "will a film work on this box":

```bash
immich-memories preflight        # one row per check: OK, WARNING, ERROR or SKIPPED
immich-memories preflight -v     # adds a Details column
```

In Docker: `docker compose exec immich-memories immich-memories preflight`.

It checks the Immich connection and API key (and each extra account), the model files and their digests,
the title renderer, hardware encoding, the output folder, the home base, config paths that don't exist on
this machine, notification delivery, the memory the box has, and every server you configured: caption
server, text model, render worker, and ACE-Step when it is set to run on this machine. It also prints one row per outside host you switched on
([Privacy](../privacy.md)). A warning names what is missing and the cut still runs
without it, for example `Music (ACE-Step)` falling back to a bundled track. Any error exits 1, so a
script or a setup step can stop on it. Run it after an install, an upgrade or a config change.


For an explicitly requested local model check:

```bash
immich-memories capabilities --verify-local
```

This executes synthetic reader/vision and configured local audio checks. It does not download
missing models. Use it after installing local runtimes; ordinary `capabilities` reports the
configuration without this verification work.

## Health endpoints

| Endpoint | Returns | Use it for |
|---|---|---|
| `GET /health/live` | `200` while the web process answers, `{"status": "alive", "version": …}`. Never contacts Immich | liveness probe |
| `GET /health/ready` | `200` with `status: ready` when configuration and authenticated Immich access work; `503` with `status: degraded` otherwise | readiness probe, Uptime Kuma, blackbox exporter |
| `GET /health` | always `200`: a ready payload is rewritten to `ok`, a degraded one passes through as `degraded` | compatibility only, never a probe |

All three are unauthenticated, on purpose: a container runtime has no session. The Immich check is
bounded at 5 seconds, and the answer is reused for up to 10 seconds so a busy poller doesn't hammer
Immich. With login on, only a logged-in session sees the automation and run detail (it carries
person names and paths); a probe gets the status and the version. A degraded status never stops
the app: the UI still serves.

Example for an authenticated session (unauthenticated probes receive reduced detail):

```json
{"status": "ready", "immich_reachable": true, "last_successful_run": "2025-12-15T10:30:00", "version": "<the running version>"}
```


## Logging

`INFO` by default. `immich-memories -v generate …` logs at `DEBUG`; `--log-level WARNING` keeps
warnings and errors. Both are root options, so they go before the subcommand and work for `ui` too.
In a container, set `IMMICH_MEMORIES_LOG_LEVEL=DEBUG`. `generate --quiet` and `auto run --quiet`
change what the terminal shows, not what is logged.

Lines look like `2025-12-15 10:30:00,123 [INFO] immich_memories.generate [abc123]: Assembling final
video...`: the bracketed run id ties one run's lines together (`-` outside a run).
`IMMICH_MEMORIES_LOG_FORMAT=json` writes one JSON object per line with the same fields, so
`jq 'select(.run_id=="abc123")'` works. `IMMICH_MEMORIES_LOG_FILE=/path/to/file.log` writes the
same lines to a file as well; in Docker, point it at a mounted path.

Log lines go to stderr. Stdout only carries what a command prints, so `runs storage --json`,
`report --json` and `auto status --json` give you one JSON document you can pipe straight into
`jq`, whatever the log level. `docker logs` shows both streams.


## Model files

```bash
immich-memories models fetch
```

Run it on installation and after an upgrade. NAS fetches the encoder and WordNet; GPU/Full also
fetch detectors and Laya. An enabled owned local reader also fetches its pinned reader/model
projector; custom GGUF paths remain your responsibility. Matching pinned files are reused. `--force` downloads again;
`--detectors` fetches detectors even on NAS. `--no-detectors` skips them, but does not make a
GPU/Full cut work without required models.

## Find the run's output

Docker:

```bash
docker compose logs -f immich-memories
```

Kubernetes:

```bash
kubectl logs -n immich-memories deploy/immich-memories -c immich-memories -f
```

Web jobs keep their own output under `cache/web-jobs/`; daily automation uses
`cache/automation-output/`. These are on the persistent data volume.
For selection-model costs, inspect the attempt's `llm-usage.json`; token totals are a lower bound
when a provider does not report usage.

## Model usage records

Selection attempts record model calls, cache hits and token counts in `llm-usage.json` beneath
`cache/editorial-runs/`. [Reader setup](../../better/reader.md) explains service behavior.

## Caches

[Storage and backups](./storage-backups.md#caches) covers disk growth and safe cleanup.

### Clearing

[Clear only disposable caches](./storage-backups.md#clearing), while idle.

### Moving an install

[Move config, keys and the store](./storage-backups.md#moving-an-install).

### What a second cut asks again

Compatible facts are reused. New inputs or changed producers may need preparation again.
[Detector versions](../reference/detector-facts.md) explain reuse and refresh.

### The facts a cut measures

[Selection internals](../../reference/selection-internals/pixel-evidence.md) describe banked measurements.

### The preview cache scales with your library

[Preview sizing](./storage-backups.md#caches).

### Video cache mechanics

Downloaded files are checked before reuse; incomplete downloads are not treated as valid hits.
