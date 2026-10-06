---
title: Automation decisions and trigger API
---

# Automation decisions and trigger API

`immich-memories auto run` is the single daily entry point. It looks at your library, decides which one memory
is worth making today (a trip that ended last week, a birthday two days ago, last month's highlights, a year
nobody cut yet), makes it, and exits. Schedule it once a day and the films arrive on their own.

```bash
immich-memories auto suggest            # what would it make today, and why
immich-memories auto run --dry-run      # the decision, without the render
immich-memories auto run                # decide and do it
```

It works on a plain NAS, and makes the same cuts you would get by hand there; a GPU or a model makes them better.

<Diagram name="seq-scheduled-run" headline="Once a day it checks what's due and makes one film at most." />
## Docker: switch on the built-in timer

In Docker the container's only process is the web UI, so the timer lives there. One setting:

```yaml
advanced:
  automation:
    enabled: true        # default false
    daily_at: "09:00"    # the container's local time (set TZ=)
```

Or add `IMMICH_MEMORIES_AUTOMATION__ENABLED: "true"` and
`IMMICH_MEMORIES_AUTOMATION__DAILY_AT: "09:00"` to the app's Compose `environment:` block
and set the time there. A line in `.env` alone
does not reach the container. Recreate with `docker compose up -d`.
Settings also exposes **Automation > enabled** and **daily_at** while those Compose lines are absent.
Either `automation.upload_to_immich: true` or `upload.enabled: true` requests delivery to Immich; `upload.album_name` names the destination. Confirmed delivery removes the local copy.

The UI process then runs the same `auto run` decision once a day, with the same lock, history, upload retry
and notifications as the CLI. A container that was down at `daily_at` catches up when it starts; if the day's
run already happened (a manual `docker compose exec immich-memories immich-memories auto run` counts) it waits
for tomorrow. A dry run does not count: a **Check eligibility** or an `auto run --dry-run` earlier that
day leaves the scheduled film in place. A manual `auto run` in progress holds the same automation lock, so the timer's attempt never
starts and leaves no attempt row: `auto history` and `auto status` never show it. A manual `generate` in
progress holds a different lock (the pipeline lock, not the automation lock), so the timer's own attempt
does start, its child `generate` then fails to get the pipeline lock, and the attempt ends `failed`, not
`skipped`. `/health/ready` shows the timer under `in_process_scheduler`.

## Bare metal: auto install

```bash
immich-memories auto install --hour 9
```

This writes a launcher at `~/.immich-memories/bin/immich-memories-auto` and scheduler files: a launchd plist on macOS, a systemd user timer on Linux, or a crontab command to paste elsewhere. It prints **Activate:** and **Deactivate:** commands; it does not run them. Run the printed activation command to start the schedule. The launcher looks `immich-memories` up on every fire, so an upgrade in place needs no reinstall.

On headless Linux, enable lingering so the user timer survives logout:

```bash
loginctl enable-linger "$USER"
```

Before `immich-memories auto install --uninstall`, run the printed deactivation command: `launchctl unload` on macOS or `systemctl --user disable --now immich-memories-auto.timer` on Linux. Uninstall deletes the launcher and scheduler files without unloading a running schedule. After removing systemd files, run `systemctl --user daemon-reload`. For cron, remove the pasted entry before deleting its launcher.

Three things a scheduled job does differently from your shell:

- it does not inherit your environment. `auto install` copies `PATH` and the ACE-Step and torch variables it
  knows, nothing else; credentials belong in the config file;
- it refuses a git worktree or a checkout behind its upstream, because a nightly job on stale code looks fine
  in the logs (`--force` overrides);
- `--config` goes before `auto`, and the installed job keeps the resolved path.

On macOS a missed job runs when the Mac wakes; launchd does not wake it.

The launchd job writes its wrapper output to `~/.immich-memories/logs/auto.log` and `auto-error.log`.
The systemd unit sets no `StandardOutput`, so its output goes to the user journal, which a user outside
`systemd-journal` may not be allowed to read. The per-attempt transcript under the cache is always
readable by its owner: see [where a scheduled run's logs go](../make/automate.md#where-a-scheduled-runs-logs-go).

## How it picks one memory

Ten detectors propose candidates, hard rotation rules reject some, the rest are scored, and the top one is
made. The score ranks memories against each other; it never touches which pictures go in a film. That is the
editor's job, see [How it chooses](../how-it-chooses/overview.md).

| Detector | Proposes | Score |
|---|---|---|
| Yearly | past years with content, after 15 January | 0.8, 10 % off per year of age, floor 0.24 |
| Birthday | a person whose birthday was 2 to 60 days ago | 0.75 |
| Monthly | the latest completed month, if not made yet | 0.7, and it never looks further back |
| Activity burst | a month with more than 2× the rolling 12-month average | 0.7 once over the threshold |
| Trip | trips in the trailing year, 7 days after coming home | up to 0.75, by length (14 days) × pictures (200) |
| Person spotlight | the five most-pictured people | 0.6 × their share of the top person's count, floor 0.12 |
| Multi-person | pairs who appear together | 0.55, by estimated shared pictures up to 500, 50 minimum |
| On this day | today, when its month has content in 5+ prior years | 0.35 × prior years / 10, capped at 0.35; month counts do not prove pictures exist on this exact date |
| Special day | a catalogued day whose anniversary is within 3 days | 0.8, ×1.0 for a decade, ×0.85 for a half-decade, ×0.6 otherwise |
| Saved group | last year's film of each [saved group](../run/multi-account.mdx#saved-groups), once | 0.65, counted as multi-person |

Then, in order: a 1.2× boost for a memory that does not exist yet, recency (linear decay over 365 days from
when the memory is timely, floor 0.5), content richness (up to 30 % of the score, log scale), and a same-type
cooldown (0.3× for 7 days, 0.7× for 30 days). Per-type caps: 3 per type, 1 for on-this-day and special day, 2
for multi-person.

The rotation rules are hard. If every candidate is rejected the run is skipped; nothing relaxes a rule to get
another video out:

- a monthly review cannot run twice in the same calendar month; the monthly detector proposes only the latest completed month, while activity bursts can propose months from the trailing year;
- the previous category cannot repeat;
- a category cannot appear more than twice in the last six completed automatic runs;
- a person cannot come back if they were in either of the last two person runs.

Timing: birthdays fire 2 days after the date and trips 7 days after coming home, so the phone has uploaded.
Trips need `trips.homebase_latitude` and `trips.homebase_longitude` (see
[Home and people](../get-started/who-is-who.md)). Special days come from the catalogue `discover-days`
writes. A birth date you gave the people store wins over the one Immich holds. Automation passes that resolved month and day explicitly to `generate --birthday`, including a leap-day birthday.

`auto suggest` prints eligible candidates in rank order with their reasons. Its terminal output also names failure-backoff skips; it does not list rejected candidates or their rotation rules. `auto status` shows current rejection rules. A candidate that failed twice in a row waits before it comes back (24 hours, then 3 days, then 7);
one failure never counts, and a success clears it.

## Across accounts, and saved groups

With a [second Immich account](../run/multi-account.mdx) connected, name the accounts automation reads:

```yaml
advanced:
  automation:
    accounts: ["primary", "partner"]  # empty reads the primary alone
    detect_groups: true               # the default
```

The list is exactly what is read: `["partner"]` alone leaves the primary library out, and trips with it. Every
candidate but a trip carries that scope to its `generate --accounts` run; trips always come from the primary
account.

`detect_groups` proposes one `multi_person` film of last year for each saved group (`people group add`). A
group's film is not proposed again once made, and a group none of whose people is among the most-pictured
people discovery counts is skipped. It shares the multi-person cap and rotation rules. The whole walkthrough:
[A second Immich account](../run/multi-account.mdx#what-automation-does-across-accounts).

## What auto run does, exactly

One action per run, one memory per invocation: retry the oldest pending upload if there is one, otherwise make
the top candidate. `--cooldown` (`automation.cooldown_hours`, 24) is measured from the last run's start with
30 minutes of slack, so a daily timer fires every day. `--candidate KEY` runs one exact `memory_key` from
`auto suggest --json`; the rules still apply, `--force` skips only the cooldown, and a stale key fails rather
than making something else.

<Diagram name="state-scheduled-attempt" headline="Every attempt ends one of four ways, and the lock always comes back." />
The outcomes are `skipped`, `dry_run`, `completed` and `failed`; the first three exit 0.
Quiet output is a stable JSON object with `runtime` as its first key. Key a wrapper on `outcome`: `action` is
`generation` or `delivery_retry`. Logging is disabled during `auto run --quiet`; its result is one JSON line, not formatted multiline output.

**Known limitation:** an attempt killed mid-run (the process is terminated rather than exiting on its own)
stays recorded as `running` forever. `auto status` and the trigger API's `status_url` both keep reporting it
as active, since nothing marks it otherwise. Restarting the app does not clear it; recognise this case by an
attempt whose `started_at` is far in the past with no `finished_at`.

```json
{"runtime": {"version": "<running version>", "checkout": null, "commit": null, "upstream": null, "commits_behind": null, "stale": false}, "outcome": "dry_run", "action": "generation", "reason": "dry run", "candidate_key": "trip:2026-07-02:2026-07-09:", "category": "trip", "run_id": null, "error": null, "output_path": null, "recent_categories": ["monthly_review", "birthday"], "rejections": []}
```

An upload that keeps failing is dropped after `automation.max_delivery_attempts` (5) tries, with a notification
carrying the error; the video stays on disk. If the output or cache volume is running low
(`output.min_free_space_gb`, 5 GB by default), a completed run's notification carries that warning too, and a
film that would not fit at all fails the attempt with the same message before anything is rendered: this is the
one place a headless cron deployment sees it, since nobody is watching a terminal. Every attempt writes its full
output to `automation-output/<attempt-id>.private.log` under the cache (owner-readable, credentials redacted,
downloadable from the **Runs** page). `auto status` shows the running code's version and commit, the timer, the
last attempt, the cooldown, notification health and pending deliveries. It refreshes discovery and exposes its outcome/error under `suggestion`, without naming the next candidate; use `auto suggest` for that.

## Check on it

```bash
immich-memories auto status             # timer state, last attempt, cooldown and delivery health
immich-memories auto status --json      # the same, for a script or jq
immich-memories auto history --limit 5  # the last five films it made on its own
```

`auto history` lists only completed automatic runs; a film you made with `generate` or the web UI is in
`runs list` ([runs](../make/cli/runs.md)). In Docker, prefix each with `docker compose exec immich-memories`.

## Get told when it runs

Notifications go through [Apprise](https://github.com/caronc/apprise), so one URL per target covers ntfy,
Discord, Telegram, email and more than a hundred others. They are off by default:

Use `ntfys` for HTTPS. Public ntfy topics can be read by others; personal run details belong in
a private, authenticated topic.

```yaml
advanced:
  notifications:
    enabled: true
    urls:
      - "ntfys://ntfy.sh/my-topic"
    on_success: true
    on_failure: true
```

```bash
immich-memories auto test-notification
```

`auto test-notification` sends one message to every URL and says whether it went through. It ignores the
cooldown that follows a failed delivery (`cooldown_hours`, 24), and a test that succeeds clears it. Every film
then sends one: `auto run`, the Docker timer and a plain `generate`. The message carries the memory type, the
outcome, the duration, the output path and, on a failure, the first 200 characters of the redacted output
(often the lead-up to the error, not the error itself); no picture unless you set
`attach_thumbnail: true`. The URLs hold credentials, so `config show` masks them and the database stores them encrypted.
Every key is in the [config reference](config-reference.md#notifications).

## Trigger it over HTTP

One POST starts the decision `auto run` would have made, on the same detectors, rules, cooldown and history.
You choose *when*, not *what*: an Immich workflow when an album fills up, a cron on another box, a phone
shortcut, Home Assistant.

The app serves the route only when something can authenticate the caller, because this process holds your
Immich API key.

| `auth.enabled` | `server.trigger_token` | `POST /api/trigger` |
|---|---|---|
| off | unset | **404**: the route is not enabled |
| off | set | token required |
| on | unset | logged-in session required (browsers only) |
| on | set | token **or** session |

```bash
export IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN="$(openssl rand -hex 32)"

curl -X POST https://memories.example.com/api/trigger \
  -H "x-api-key: $IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN"
```

For Docker, put `IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN=your-generated-token` in `.env` and run
`docker compose up -d`. The shipped Compose file forwards this key. Use the same token in the
caller's `Authorization: Bearer` header.

Keep the token in the environment: `server` is not a section that expands `${VAR}`, so `"${SOMETHING}"` in
`config.yaml` is those literal characters. It must be 32 random characters or more, without placeholder words
like `change-me`; a shorter token stops the app at startup. It is compared in constant time and redacted from
logs, `/health` and the config viewer. Send it only over HTTPS, behind the same reverse proxy as the web UI.

A caller that sends no `Origin` header (curl, a CronJob, Home Assistant) needs no change. One that sends an
`Origin` naming another site gets **403**. With auth off, the app answers only a local host or one in
`server.allowed_hosts`; the shipped Kubernetes CronJobs send `Host: localhost` for that reason. See
[Allowed hosts](../run/network-security.md#allowed-hosts).

The answer is `202 Accepted` with an `attempt_id` and a `status_url`; `Authorization: Bearer <token>` works too.
**401** means authentication failed (`{"detail":"invalid trigger token"}`). **409** means a run is already going, and the body names it. GET the `status_url` for attempt fields: `attempt_id`, `state`, `reason`, `started_at`, `finished_at`, `phase`, `memory_type` and `error`. The final `state` is `completed`, `failed`, `skipped` or `dry_run`. Its `run` is null until a run exists, then holds `run_id`, `status`, timestamps, `last_phase`, `output_duration_seconds`, `delivery_status` and `immich_asset_id`.

`skipped` is a normal answer: a workflow that fires on every upload mostly gets it back, and one that fires on a
trip album asks for the best candidate right now, not for that album. For a specific film, use the CLI or the
web UI.

## Kubernetes

`deploy/kubernetes/base/cronjobs.yaml` contains two HTTP-trigger CronJobs. They read only the
trigger token from `immich-memories-secrets`, mount no application PVCs, and call
`POST /api/trigger` on the running Deployment. Both schedules use the normal `auto run`
decision; the one named monthly does not force a monthly film.

Set the trigger token, add `- cronjobs.yaml` to `base/kustomization.yaml`, then render and apply:

```bash
kubectl kustomize deploy/kubernetes/base
kubectl apply -k deploy/kubernetes/base
```

The base NetworkPolicy permits their app-pod backend on 8080 after Service-port translation.
The separate `base/job.yaml` runs a one-off `generate` command and mounts the SQLite PVCs;
include it only with the Deployment scaled to zero. For a fixed recipe while the app runs,
use `kubectl exec ... -- immich-memories generate ...` so there is no second SQLite writer.

## A named memory on a named date

The one thing `auto` cannot say is "a year in review every 15 January". A cron line that runs `generate` says it. The shipped Kubernetes monthly trigger uses the normal `auto run` decision and does not force a monthly film. Replace `/absolute/path/to/immich-memories` with the installed executable and set cron’s `PATH` to include FFmpeg and other required tools:

```bash
# 15 January, 09:00: last year's review, uploaded to an album
0 9 15 1 * /absolute/path/to/immich-memories generate --memory-type year_in_review --year $(( $(date +\%Y) - 1 )) --upload-to-immich --album "Memories"
```
