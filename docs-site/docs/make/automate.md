---
title: Automatic films
description: Let the app choose and make one worthwhile memory film each day.
---

# Automatic films

`immich-memories auto run` is the single daily entry point. It chooses one memory worth making today: a recent trip, a birthday, last month's highlights or a year you have not cut yet. If nothing qualifies, it skips the day.

Make and review a few films manually first. Set [home and people](../get-started/who-is-who.md), then check **Suggestions** to see what it would choose.

## Docker: switch on the built-in timer

Fetch the models first, or the first fire fails on a missing encoder:

```bash
docker compose exec immich-memories immich-memories models fetch
```

Then, in `docker-compose.yml`, add these two lines under the app's `environment:` block:

```yaml
IMMICH_MEMORIES_AUTOMATION__ENABLED: "true"
IMMICH_MEMORIES_AUTOMATION__DAILY_AT: "09:00"
```

Change the time there, then recreate the container:

```bash
docker compose up -d
```

The time uses the container's timezone (`TZ`). Upload is a separate choice: either `automation.upload_to_immich: true` or `upload.enabled: true` enables delivery for automatic films. Set `upload.album_name` for the destination. Complete upload, provenance tagging and requested album delivery remove the local copy. If the key lacks any of the five upload permissions (including album rights when no new album is needed), generation still completes: the local film stays, the run names the missing permission, and automatic retries stop for that film. Temporary tagging or album failures stay pending for the existing bounded retry process. Permitted steps still run, so a film may be uploaded while tagging or album delivery remains incomplete. A key without `asset.delete` keeps the previous uploaded version and records why. Leave both upload switches false to keep films on disk.

Or omit those Compose lines and save **Settings > Automation > enabled** and
**daily_at**. Settings also holds the other automation options; file and environment values win.

## Bare metal: auto install

```bash
immich-memories auto install --hour 9
```

This writes a user timer on macOS or Linux and prints its activation command. Run **Activate:** to start it; installation alone does not activate the schedule. On headless Linux, run `loginctl enable-linger "$USER"` so the timer survives logout. Run **Deactivate:** before `auto install --uninstall`, which only deletes files. Scheduled jobs do not inherit your interactive shell's credentials: keep them in the configuration. [Scheduler details](../reference/automation-contract.md#bare-metal-auto-install) cover the launcher, environment and missed runs.

### Where a scheduled run's logs go

Every attempt that starts a film keeps its full output, credentials redacted, in
`~/.immich-memories/cache/automation-output/<attempt-id>.private.log`. It's your file (mode 0600):
no sudo, no journal access needed. **Runs** in the web UI has a download button for it too.

```bash
immich-memories auto status                  # last attempt, outcome and reason
ls -t ~/.immich-memories/cache/automation-output/ | head -1   # newest transcript
```

That path moves with `cache.directory` if you changed it. A day skipped before any film starts (cooldown, every candidate rejected) leaves no
transcript: `auto status` says why.

The scheduler's own wrapper output goes elsewhere. On macOS it lands in
`~/.immich-memories/logs/auto.log` and `auto-error.log`. On Linux the systemd unit sends it to your
user journal: `journalctl --user -u immich-memories-auto.service` works only if your distribution
keeps per-user journals or you're in the `systemd-journal` group. On a stock Ubuntu account that
answers "insufficient permissions", so read the transcript above instead.

## How it picks one memory

It ranks suitable memories and avoids repeating the same category or person too often. That choice selects the subject; the normal editor still chooses the shots. Trips wait until after you are home and birthdays wait a little for phone uploads.

**Suggestions** shows each reason. **Check eligibility** previews the checks, and **Run this suggestion** asks for that candidate. A manual request still respects the automation rules.

## Check on it

Open **Runs** for completed films and failures. On the CLI:

```bash
immich-memories auto status
immich-memories auto history --limit 5
```

For a safe preview:

```bash
immich-memories auto run --dry-run
```

## Get told when it runs

Notifications support ntfy, email, Discord and other Apprise targets. Configure the URLs, then test them:

In Docker, first [set `IMMICH_MEMORIES_SECRET_KEY` in `.env`](../run/config-file.md#secrets-in-the-database)
and recreate the container. Then save **Settings > Notifications > enabled** and **urls**.
The URLs contain credentials, so saving them needs that encryption key. YAML is another route:

```yaml
advanced:
  notifications:
    enabled: true
    urls:
      - "ntfys://ntfy.sh/my-topic"
```

```bash
immich-memories auto test-notification
```

The test sends a message to each configured target. Films then report completion or failure. Thumbnails remain off unless you enable them.
`ntfys` uses HTTPS. Public ntfy topics can be read by others; use a private, authenticated topic
for personal run details.

## Trigger it over HTTP

[The trigger API](../reference/automation-contract.md#trigger-it-over-http) is for Home Assistant, shortcuts or another scheduler. It asks automation to choose a memory; it does not film whichever album caused the trigger.

The [automation reference](../reference/automation-contract.md) covers scores, rotation, delivery retries, tokens, HTTP responses, multi-account scope and Kubernetes. [Configuration keys](../reference/config-reference.md#automation) have the defaults.
