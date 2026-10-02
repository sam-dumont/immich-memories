---
title: Automatic films
description: Let the app choose and make one worthwhile memory film each day.
---

# Automatic films

`immich-memories auto run` is the single daily entry point. It chooses one memory worth making today: a recent trip, a birthday, last month's highlights or a year you have not cut yet. If nothing qualifies, it skips the day.

Make and review a few films manually first. Set [home and people](../get-started/who-is-who.md), then check **Suggestions** to see what it would choose.

## Docker: switch on the built-in timer

In `docker-compose.yml`, uncomment these two lines under the app's `environment:` block:

```yaml
IMMICH_MEMORIES_AUTOMATION__ENABLED: "true"
IMMICH_MEMORIES_AUTOMATION__DAILY_AT: "09:00"
```

Change the time there, then recreate the container:

```bash
docker compose up -d
```

