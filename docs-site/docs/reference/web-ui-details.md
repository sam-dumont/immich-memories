---
title: Web UI configuration and job behavior
---

# Web UI configuration and job behavior

Operator details for the browser client. The task guide is [Use the web UI](../make/web-ui.mdx).

**Cut** runs `generate --no-render` on the server. The panel shows the stage, its count and the last
pictures it read. With a previous completed run, the bar and time left cover the whole cut: saved
stage times scale to this picture count, and the current stage uses its measured speed. Without
history, the total time stays unknown, so the bar follows the current stage and the panel shows the
time left in that stage. On a library that has never been read, *Reading dates, places
and people* is the long one; a later cut over the same pictures reuses what it banked. The stages:
[From library to film](../how-it-chooses/overview.md).

**Copy as CLI command** copies an equivalent command for the cut or render. It omits the server's
executable and config paths, and its output or progress-file paths. The cut runs on the server, not in the tab. Reload, close the laptop, come back: the page finds the
running cut and follows it again. **Cancel** stops it. A cut that fails shows the command's own last
lines, and keeps showing them after a reload, because they usually name the command that fixes it
(`immich-memories models fetch` on a fresh install). One job runs at a time.
The job API accepts saved job IDs; a missing or invalid ID returns HTTP 404.


## Saved revisions

**Keep the original** undoes a swap. The sheet marks removed and swapped shots. A bar at the bottom counts the changes and adds up the
seconds; past what the titles left, it says the film grows to hold them. Your edits are the last
pass, so length never refuses one. **Undo** (or Ctrl/Cmd+Z) walks back one change; **Discard changes** drops them all.

**Save revision** keeps the edits as a numbered revision beside the run
(`revisions/0001.private.json` in its attempt folder). It only refuses what the renderer cannot
play, like a trim past the end of a video, and says which edit. **Revisions** lists every saved
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
change on restart. Changing a server URL that receives a credential needs that credential typed in
the same save; otherwise the page says "The server URL changed: enter the credential for the new
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

**Caches** lists the two caches a run fills, with their size and a **Clear** button each.

| Cache | Holds | Cost of clearing |
|-------|-------|------------------|
| **Video cache** | downloaded source videos | re-download from Immich; evicted on its own anyway |
| **Thumbnail cache** | Immich previews, read back for pixel facts, heads, contact sheets and the grid | re-fetched on demand |

The expensive thing on disk is not behind those buttons. The editor's bank lives in the store
(`store.db`), not under the cache directory, and holds every fact it read about your pictures.
Delete it and the next cut reads your library from scratch. More on [Health, logs and caches](../run/maintenance/health-logs-cache.md).
