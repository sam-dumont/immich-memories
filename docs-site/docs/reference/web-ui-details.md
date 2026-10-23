---
title: Web UI configuration and job behavior
---

# Web UI configuration and job behavior

Operator details for the browser client. The task guide is [Use the web UI](../make/web-ui.mdx).

<Diagram name="seq-web-job" headline="Cut first, look at it, then render. Nothing renders until you press the button." />
**Cut** runs `generate --no-render` on the server. The panel lists the job's phases (done, current,
pending, skipped) with the elapsed time and time left for each, the current stage's count and the last
pictures it read. The overall estimate covers every phase left in the job, from this run's measured
rate and earlier runs with the same tier and output settings; until it has one, the panel shows the
time left in the current stage. On a library that has never been read, *Reading dates, places
and people* is the long one; a later cut over the same pictures reuses what it banked. How the
estimates are made: [Film progress and recovery](../run/film-progress.md). The stages:
[From library to film](../how-it-chooses/overview.md).

**Copy as CLI command** copies the equivalent command for the cut or render, without the server's
executable, config, output and progress-file paths.

The cut runs on the server, not in the tab. Reload, close the laptop, come back: the page finds the
running cut and follows it again. **Cancel** stops it. A cut that fails shows the command's last lines,
after a reload too, because they usually name the fix (`immich-memories models fetch` on a fresh
install). One job runs at a time. A missing or invalid job ID returns HTTP 404.

A job's own record is `running` until it ends `succeeded`, `failed` or `cancelled` (**Cancel**
sends SIGTERM to the whole process group). A server restart or crash while a job is running
leaves it `running` with no process behind it; the next time the page asks for it, that gap is
read as `interrupted` instead of staying `running` forever.

### Input and saved edits

Two saves at once get two numbered cut revisions. Invalid JSON, NUL characters, unpaired Unicode
surrogates and nesting beyond 64 levels return a client error before a job starts. A music upload
needs an audio stream with a positive duration; a truncated file is refused, and if the server can't
probe audio, the page asks you to install FFmpeg.

If the cache, output or database storage fills up, the API returns a storage-full message (HTTP 507),
and a job that fails for that reason shows the same advice under its status, even when the disk couldn't
hold a complete log. Free space or expand the volume before retrying; don't delete the store. A failed
revision save keeps the earlier revisions. A job whose first record can't be saved is stopped before the
error returns, so nothing runs that the page can't follow or cancel.

## Saved revisions

**Keep the original** undoes a swap. The sheet marks removed and swapped shots. A bar at the bottom
counts the changes and adds up the seconds; past what the titles left, it says the film grows to hold
them. Your edits are the last pass, so length never refuses one. **Undo** (or Ctrl/Cmd+Z) walks back
one change; **Discard changes** drops them all.

**Save revision** keeps the edits as a numbered revision beside the run, in its attempt folder. It only
refuses what the renderer can't play, like a trim past the end of a video, and says which edit. **Revisions** lists every saved
one; **Open** loads it back into the editor.

## Settings and configuration sources

**Immich Connection** is the server and API key this install reads. The key field always loads empty:
the saved key stays on the server, and an empty field keeps it. Change the URL and you type the key
again, because a saved key only ever goes to the server it was saved for. **Test Connection** asks
the server who the key belongs to without saving. **Save Config** saves what you changed, and only
that, to the database. A URL or key the environment or `config.yaml` sets is refused with the name of
what sets it, and the key is a secret, so saving it needs `IMMICH_MEMORIES_SECRET_KEY`.

**Configuration** lists every setting, grouped by section, with its live value and where it comes from:

| Label | Source |
|---|---|
| Set by `IMMICH_MEMORIES_LLM__MODEL` (environment) | an environment variable, named exactly |
| Set in config.yaml as `advanced.llm.model` | `config.yaml`, named the way the file writes it |
| Saved here | the database, saved from this page or the CLI |
| Default | nothing set it |

The strongest source wins: environment, then `config.yaml`, then the database, then the default
([precedence](../run/config-file.md#where-a-setting-comes-from)). A setting the environment or
`config.yaml` sets is greyed out: saving under it would change nothing, so change it where the label
says, or move it out of the file with `immich-memories config move-to-db KEY`. The **auth** and
**server** sections are always greyed out: they are set in the environment or `config.yaml` and
change on restart. So are the render worker address and token, the local reader program
(`llm.local_server`) and the model-file and detector paths. Changing a server URL that receives a
credential needs that credential typed in the same save; otherwise the page says "The server URL changed: enter the credential for the new
server." A value containing `${` is refused. Everything else is
editable, and each section's **Save** writes only the keys you changed, to the database. The page never
writes `config.yaml` or the environment. Lists and mappings are edited as JSON. **Reload from Disk**
re-reads the file (its path is shown as **Config file**) after a hand edit.

Any key named `api_key`, `api_keys`, `caption_api_key`, `client_secret`, `password`, `secret`, `token`,
`trigger_token`, `worker_token` or `urls` is a secret: it shows as `***`, masked on the server, and an empty field
keeps the stored value. Secrets are encrypted in the database with `IMMICH_MEMORIES_SECRET_KEY`;
without it the page greys them out and says "Secrets cannot be saved here until
IMMICH_MEMORIES_SECRET_KEY is set". That is fine if your keys already come from `.env` or
`config.yaml`. To save them here, generate a key with `openssl rand -base64 32` and set it in the
environment; on Docker that is one line in `.env`, which the compose file passes through
([The secret key](../run/environment-variables.md#the-secret-key)). A secret marked "Saved here, but
IMMICH_MEMORIES_SECRET_KEY cannot decrypt it" was saved under a different key: the default is in use
until you save it again. Every key:
[configuration reference](../reference/config-reference.md).

**Checks** shows what loading your config warned about (removed, unknown or unsupported keys, a
reader set up but switched off) and the rows `immich-memories preflight` prints. These are
the same lines the server log carries, so a Docker or NAS install sees them without reading the
container log. They name keys, never values. The preflight rows wait for **Run the preflight
checks**: they ask Immich and the reader and probe the encoder, which takes a few seconds.

**Updates** has a **Check for updates** button: one anonymous request for GitHub's public release list,
sent only when you click. A newer release comes with its notes and the update command for this kind of
install. With `updates.check_daily` on, the app checks once a day and shows a banner you can dismiss.

**Caches** lists the three caches a run fills, with their size and a **Clear** button each.

| Cache | Holds | Cost of clearing |
|-------|-------|------------------|
| **Video cache** | downloaded source videos | re-download from Immich; evicted on its own anyway |
| **Thumbnail cache** | Immich previews, read back for pixel facts, heads, contact sheets and the grid | re-fetched on demand |
| **Prepared-source cache** | cut segments, merged Live Photos and animated photos a re-render reuses (`<cache.directory>/prepared-sources`, capped by `advanced.analysis.prepared_source_cache_max_size_gb`) | the next render prepares them again |

The expensive part isn't behind those buttons. The editor's bank lives in the store (`store.db`), not
under the cache directory, and holds every fact it read about your pictures. Delete it and the next cut
reads your library from scratch. More on [Health, logs and caches](../run/maintenance/health-logs-cache.md).
