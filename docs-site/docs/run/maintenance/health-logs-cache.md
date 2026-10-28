---
title: "Diagnostics and monitoring"
---

# Diagnostics and monitoring

Start with preflight when a film fails. Health endpoints are for monitoring the running web process.

## Preflight

The health endpoints say whether the web process is up. `preflight` says whether a film will work
on this machine:

```bash
immich-memories preflight        # one row per check: OK, WARNING, ERROR or SKIPPED
immich-memories preflight -v     # also fills in details for the OK rows
```

WARNING and ERROR rows always show their cause and fix in the Details column.
In Docker: `docker compose exec immich-memories immich-memories preflight`.

It checks the Immich connection and API key (and each extra account), the model files and their digests,
the title renderer, hardware encoding, the output folder, the home base, config paths that don't exist on
this machine, configured notification readiness and saved delivery health, the memory the box has,
and configured service endpoints: caption server, text model, render worker, and ACE-Step when
it is set to run on this machine. It does not send a notification. Its **Outside call** rows name
enabled geocoding and map destinations, not every outside endpoint ([Privacy](../privacy.md)).
A warning names what is missing and the cut still runs
without it, for example `Music (ACE-Step)` falling back to a bundled track. Any error exits 1, so a
script or a setup step can stop on it. Run it after an install, an upgrade or a config change.

The reader check waits up to 10 seconds per HTTP operation. If a connected reader times out while
sending its answer, its row says **Reader is slow to answer**; retry once the server is idle. This
changes only the preflight probe; `llm.timeout_seconds` still controls normal reader requests.
Other preflight checks keep their own timeouts.

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
| `GET /health` | After host validation, always `200`: a ready payload is rewritten to `ok`, a degraded one passes through as `degraded`; an unaccepted host receives `421` | compatibility only, never a probe |

All three are unauthenticated, on purpose: a container runtime has no session. The Immich check is
bounded at 5 seconds, and the answer is reused for up to 10 seconds so a busy poller doesn't hammer
Immich. With login on, only a logged-in session sees configuration, Immich connection, automation
and run details. A probe gets the status and version; the detail fields are `null`. A degraded
status never stops the app: the UI still serves.

Example of `/health/ready` with login enabled and no authenticated session. Operational details
are present as `null`:

```json
{
  "status": "ready",
  "configuration": null,
  "immich_reachable": null,
  "immich": null,
  "automation": null,
  "last_automation_attempt": null,
  "last_successful_auto_run": null,
  "pending_delivery_count": null,
  "oldest_pending_delivery": null,
  "notification_health": null,
  "last_successful_run": null,
  "in_process_scheduler": null,
  "disk": null,
  "version": "<the running version>"
}
```


## Logging

`INFO` by default. `immich-memories -v generate …` logs at `DEBUG`; `--log-level WARNING` keeps
warnings and errors. Both are root options, so they go before the subcommand and work for `ui` too.
In a container, set `IMMICH_MEMORIES_LOG_LEVEL=DEBUG`. `generate --quiet` only changes what the
terminal shows. `auto run --quiet` turns logging off for the run and prints one JSON result line;
the generation's own output is still kept in the private attempt log.

Lines look like `2025-12-15 10:30:00,123 [INFO] immich_memories.generate [abc123]: Assembling final
video...`: the bracketed run id ties one run's lines together (`-` outside a run).
`IMMICH_MEMORIES_LOG_FORMAT=json` writes one JSON object per line with the same fields, so
`jq 'select(.run_id=="abc123")'` works. `IMMICH_MEMORIES_LOG_FILE=/path/to/file.log` writes the
same lines to a file as well; in Docker, point it at a mounted path.

Log lines go to stderr. Stdout only carries what a command prints, so `runs storage --json`,
`report --json` and `auto status --json` give you one JSON document you can pipe straight into
`jq`, whatever the log level. `docker logs` shows both streams.


## Traces

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to your OpenTelemetry collector's HTTP port and every run is
traced there: the `run` span at the root, with preparation, discovery, selection and render under
it, the same spans `report` shows. Spans leave as they close, so a render that takes an hour shows
up while it runs, and a run that gets killed keeps what it had already sent. Unset, nothing is sent
and nothing extra is loaded.

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_SERVICE_NAME=immich-memories   # the default
```

- **One trace from what started the run.** A film started from the web page sits under its
  `job.<kind>` span; a scheduled one sits under `automation.generate`. The run itself runs in a
  child process, which inherits the trace through `TRACEPARENT`.
- The run span carries `run.id`, `run.status`, `run.source` and the run's LLM spend
  (`llm.prompt_tokens`, `llm.stage.<stage>.completion_tokens`, ...).
- A failed stage is an error span with its exception (redacted, the app's own frames only).
  Logged warnings are span events, the first 20 per span.
- Export is OTLP over HTTP (protobuf). `OTEL_EXPORTER_OTLP_PROTOCOL=grpc` is refused with a
  warning: point the endpoint at port 4318 instead.
- The standard variables apply: `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` (used as-is),
  `OTEL_EXPORTER_OTLP_HEADERS` for a token, `OTEL_EXPORTER_OTLP_TIMEOUT` (milliseconds, as the
  spec says), `OTEL_RESOURCE_ATTRIBUTES`, and `OTEL_SDK_DISABLED=true` to switch it off.
- A collector that's down costs one warning. The run itself is never failed by it, but a process
  waits up to the timeout (10 seconds by default) for the last spans before it exits.

With `IMMICH_MEMORIES_LOG_FORMAT=json`, every line written inside a span carries its `trace_id` and
`span_id`, so a log backend can jump from the line to the trace. That includes the server's
progress lines for a scheduled run. Scheduled runs start as child processes of the server and
inherit its environment, so setting the variables on the server container covers them.


## Model files

```bash
immich-memories models fetch
```

The app's **Download models** button runs this same command during installation. Run it after
an upgrade to verify the new pins. Basic fetches the encoder and WordNet; GPU/Full also
fetch detectors and Laya. An enabled app-owned local reader also fetches its pinned model and projector; custom GGUF paths remain your responsibility. Matching pinned files are reused. `--force` downloads again;
`--detectors` fetches detectors even on Basic. `--no-detectors` skips them, but does not make a
GPU/Full cut work without required models.

## Where a run's output goes

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

- Disk growth, sizing and safe cleanup: [Storage and backups](./storage-backups.md#caches), and
  [clear only disposable caches](./storage-backups.md#clearing), while idle.
- Moving an install: [config, keys and the store](./storage-backups.md#moving-an-install).
- What a second cut reuses: compatible facts are reused, and new inputs or changed producers are
  prepared again ([detector versions](../reference/detector-facts.md)).
- The facts a cut measures: [selection internals](../../reference/selection-internals/pixel-evidence.md).
- Downloaded video files are checked before reuse; an incomplete download is never a cache hit.
