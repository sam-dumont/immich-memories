---
title: Automatic films
description: Let the app choose and make one worthwhile memory film each day.
---

# Automatic films

`immich-memories auto run` is the single daily entry point. It chooses one memory worth making today: a recent trip, a birthday, last month's highlights or a year you have not cut yet. If nothing qualifies, it skips the day.

Make and review a few films manually first. Set [home and people](../get-started/who-is-who.md), then check **Suggestions** to see what it would choose.

## Docker: switch on the built-in timer

Add this to `.env`:

```bash
IMMICH_MEMORIES_AUTOMATION__ENABLED=true
IMMICH_MEMORIES_AUTOMATION__DAILY_AT=09:00
```

Then recreate the container:

```bash
docker compose up -d
```

The time uses the container's timezone (`TZ`). Upload is a separate choice: configure `upload.enabled` and `upload.album_name` if films should arrive in Immich rather than stay on disk.

## Bare metal: auto install

```bash
immich-memories auto install --hour 9
```

This installs a user timer on macOS or Linux. Scheduled jobs do not inherit your interactive shell's credentials: keep them in the configuration. [Scheduler details](../reference/automation-contract.md#bare-metal-auto-install) cover the launcher, environment and missed runs.

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

```yaml
advanced:
  notifications:
    enabled: true
    urls:
      - "ntfy://ntfy.sh/my-topic"
```

```bash
immich-memories auto test-notification
```

The test sends a message to each configured target. Films then report completion or failure. Thumbnails remain off unless you enable them.

## Trigger it over HTTP

[The trigger API](../reference/automation-contract.md#trigger-it-over-http) is for Home Assistant, shortcuts or another scheduler. It asks automation to choose a memory; it does not film whichever album caused the trigger.

The [automation reference](../reference/automation-contract.md) covers scores, rotation, delivery retries, tokens, HTTP responses, multi-account scope and Kubernetes. [Configuration keys](../reference/config-reference.md#automation) have the defaults.
