---
title: Home and people
description: Set your home and confirm the people who matter in your films.
---

# Home and people

Two pieces of context make the cut much better: where home is, and who is close family. Immich already knows dates and faces. This app needs you to confirm what they mean.

## Where home is

A home base helps the app keep a holiday together as a trip, instead of treating it as ordinary weeks at home. Set its coordinates in decimal degrees in Docker's `.env`:

```bash
IMMICH_MEMORIES_TRIPS__HOMEBASE_LATITUDE=50.8503
IMMICH_MEMORIES_TRIPS__HOMEBASE_LONGITUDE=4.3517
```

Then apply them:

```bash
docker compose up -d
```

For a native install, use `~/.immich-memories/config.yaml`:

```yaml
trips:
  homebase_latitude: 50.8503
  homebase_longitude: 4.3517
```

`immich-memories preflight` confirms the coordinates. They stay in your configuration; online place lookup is a separate opt-in. [Trip detection rules](../reference/film-types.mdx#trip) explain the distances and gaps.

## Who's who

Name the faces that matter in Immich first. In this app, open **Settings > People**:

1. Press **Rescan the library**.
2. Set **Role** for your partner, children and parents.
3. Confirm or reject the suggested **Relationships**, and add any missing ones.

The scan reads metadata, not pictures. Your confirmations survive a rescan. Its guesses alone never make someone close family.

## What changes

Close family gets a place in the film when the period holds enough pictures of them. Their presence can make a busy day a bigger story, and an ordinary week worth keeping. A person film also uses the relationships you confirmed.

These settings apply to the next cut. Cut the same month again and compare it with the first one; you do not need to clear the preparation cache.

The [people registry reference](../reference/people-registry.md) has CLI editing, saved groups and account bindings. The exact family-seat thresholds are in the [configuration reference](../reference/config-reference.md).
