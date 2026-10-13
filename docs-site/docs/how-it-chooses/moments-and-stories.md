---
title: Moments and stories
---

# Moments and stories

A **moment** is a short stretch of pictures of the same thing: thirty frames of a jump, or ten minutes at the dog park. A **story** gives related moments a place in the film: ordinary days at home, an evening out, or a trip.

The editor spreads its shots between stories. More photos do not automatically buy more screen time. Favourites, close family, videos and time away from home all help it distinguish an occasion from another Tuesday.

Set your home location and confirm your family in [Home and people](../get-started/who-is-who.md). Otherwise it has less evidence about who matters and what counts as away.

## Days that get their own story

A birthday or a family visit doesn't get folded into its week. The editor gives it a story of its own when your library says so:

- **A birthday**: someone from your household or close family is in a picture that day, and their birth date in Immich falls on it. Kit's birthday, "Kit turns five".
- **A visit**: close family who don't live with you (your parents, say) are on at least 2 pictures that day, and on 3 photographed days of the period at most. Someone who lives with you never "visits".

Both need the facts from [Home and people](../get-started/who-is-who.md): birth dates set in Immich, and who is who in your household.

## What a story is called

Each story is named from what its pictures say, never from what an image classifier guessed they show:

- an occasion by itself: "Kit's birthday", "Lou and Pat's visit";
- a trip by the album you made for it, else the farthest place it reached ("Trip to Nordkapp"). Each leg of a long trip runs from its first place to its last ("Copenhagen to Nordkapp");
- a day out by its place and date ("Tervuren, Sunday 6 July");
- days at home by their span ("Days at home, 1–4 July").

A stay away is a trip only by your own trip settings: at least `trips.min_distance_km` from home (50 km by default) over at least `trips.min_duration_days` (2). An evening concert 11 km away is a day out.

## Chapters and pacing

A trip that changes where it stays can become separate chapters. A long film about a person spreads its shots across the years it covers. A period with little worth showing stays short.

Want to steer those choices? [Review and adjust](./overrule-it.md). Want the thresholds, event rules and shot allocation? [Grouping and allocation reference](../reference/selection-internals/moments-and-stories.md).
