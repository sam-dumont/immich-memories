---
title: Film progress and recovery
description: Follow preparation and rendering, recover interrupted work and find the finished film.
---

# Film progress and recovery

The [first-film walkthrough](../get-started/first-film.mdx) covers making a film.
This page covers a slow, failed or interrupted job. Run the commands inside the app container,
or directly on a native install; use `docker compose exec -T immich-memories` as the Docker prefix.

## Progress and recovery

| Phase | What you see | Complete when |
|---|---|---|
| Image pull | `docker compose pull` layer progress in the terminal | Pull exits successfully; `docker compose up -d` starts the app |
| Model preparation | `models fetch` downloads or verifies pinned files | Command succeeds, then preflight passes the required checks |
| Input preparation and cut | Memory page stage, picture counts and elapsed time | The page opens the saved run (“The cut is ready.” may flash by first) |
| Review | Shots, Pool and saved revisions on the run page | You select the revision you intend to render |
| Render | Render progress on the run page | “The film is ready.”, player and Download film |

Use `docker compose logs --tail=100 immich-memories` for server/startup errors. Generation
runs as a separate job: use its progress/error panel and the run's **Copy report**, or
`immich-memories report RUN_ID`, for run diagnostics. A first job may have only a stage estimate.
The [measurements](../better/measured.md) separate warm tests from cold preparation and rendering;
no fixed first-film time is promised. A real month's first preparation can take hours on a NAS.

Press **Cancel** on an active job to cancel it; cancellation can wait for active native work.
Cancelling marks the run **Cancelled** and clears its scratch folder; the saved cut stays, so
**Render again** still works. Reloading the browser does not cancel it. Return to **Memory** for
the active cut or **Runs** for its saved cut/render. Restarting the app/container does not resume
a vanished job: the run shows as **Interrupted** after the next start. Rerun Cut if no cut was
saved, or render the saved revision again. Compatible picture facts remain cached. Keep the store
and run files.

| Problem | Diagnostic and next action |
|---|---|
| Immich unreachable or key rejected | Run preflight; correct the container-reachable URL and [read permissions](./docker.md#the-api-key) in `.env`, then `docker compose up -d` |
| Missing or wrong model pin | Run `models fetch` again, then preflight; see [offline preparation](./offline.md) if downloads are blocked |
| Output not writable | Fix UID/GID ownership of this project's `output` using [the NAS permissions recipe](./nas.md#the-output-folder), then preflight |
| Memory pressure or exit 137 | Check `docker stats --no-stream` and container state; keep Basic/1080p and give this app its own 4 GiB budget; see [render budgets](./reference/rendering.md) |
| The cut hangs on thumbnails while preflight is green | The host's network MTU is below Docker's: [set a lower Compose network MTU](../reference/troubleshooting.md#preflight-says-immich-is-connected-but-cuts-hang-on-thumbnails) |
| A cut fails with “cannot reach” your Immich | A busy or shared Immich can drop connections for several minutes in the middle of preparation. What the cut already prepared is kept: run the same command again and it fetches only what is missing. A month on a shared Immich failed after 10 minutes this way and finished on the immediate rerun, fetching 159 missing previews |
| Interrupted work | Inspect the job error and saved run, then retry Cut or Render as above; [diagnostics](./maintenance/health-logs-cache.md) explains logs and reports |

For a deliberate fresh trial or uninstall, use [the scoped lifecycle procedures](./lifecycle.md).
They are separate from retrying an interrupted film.


## Find the finished film

Open the render run under **Runs**. **Download film** is below the player; **Download report**
is the diagnostic bundle. Rendering creates its own run, separate from the cut you rendered.
Each run's film is in its own folder beneath the configured output directory.

A successful upload removes the local copy. Local-only and failed deliveries keep theirs.
[Output and rendering](../reference/output-rendering.md) documents naming and storage;
[Kubernetes file transfer](./reference/kubernetes-operations.md#getting-the-films) covers copying
from a pod when a browser download is unsuitable.
