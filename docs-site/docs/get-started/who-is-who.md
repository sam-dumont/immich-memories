---
title: Home and people
description: Set your home and confirm the people who matter in your films.
---

import ThemedScreenshot from '@site/src/components/ThemedScreenshot';

# Home and people

Two things make the cut much better: where home is, and who is close family. Immich already knows dates and faces; you tell the app what they mean.

## Where home is

A home base helps the app keep a holiday together as a trip, instead of treating it as ordinary weeks at home.
Set its coordinates in decimal degrees in **Settings**. To fix them through Docker instead,
add these entries to the app's `environment:` block in `docker-compose.yml`:

```yaml
      IMMICH_MEMORIES_TRIPS__HOMEBASE_LATITUDE: "50.8503"
      IMMICH_MEMORIES_TRIPS__HOMEBASE_LONGITUDE: "4.3517"
```

The shipped Compose file does not forward these coordinates from `.env` alone. Apply the change:

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

Name the faces that matter in Immich first. Then open **People** in this app:

1. Press **Rescan the library**.
2. Check **Account owner**. The scan only guesses whose library this is, and a lot hangs on it: what everyone is "to the library owner", the family seat, the titles. Pick the right person, or **Nobody in this library** for a shared family account. What you pick stays through every rescan.
3. Set **Role** for the people in your library. Choose the role that fits each person; partner, child and parent are examples.
4. Answer the links the scan found. It notices pairs that appear together all the time, but it cannot know what they are to each other. Under **Relationships**, pick the real one ("parent of", "partner of") and both sides get written, with the reverse kind. **No, they are not** closes the question for good.
5. Accept what your family tree implies. Once someone's parent, sibling or partner is set, the page suggests what follows: siblings who share a parent, a parent's partner as the other parent, then grandparents, aunts and uncles, nieces and nephews, cousins and in-laws, however many steps away. Each one shows its chain ("parent of Bob, who is a parent of Riley") and appears as soon as you add the link it comes from. The tick records it on both cards, **Accept all suggestions** takes a whole card, and **No, they are not** turns it down for good. Nothing counts until you accept it: the tree can't tell a half-sibling from a sibling, a step-parent from a parent, or a partner from a spouse.

<ThemedScreenshot name="people-relationship-suggestions" alt="Kit's card: child of Robin confirmed, and two suggestions with their chains, child of Charlie and grandchild of Pat, each with a tick and a cross" />

An unanswered pair shows up once among the visible cards, including when you filter by name. Naming it updates both cards. Once you name it, the scan's guess is gone, and a rescan will not bring it back. A link confirmed without a kind reads "linked, relationship not named" until you pick one. The app never guesses the kind, and until you pick it the link stays out of titles and prompts.

If **Account owner** says **not known yet**, the account name has not been matched to a named
person. Choose the owner yourself, or name people in Immich and rescan.

Each card also says how many pictures someone is in, when the first was taken, and when they became regular, if that came later. "62 pictures across 9 months, first picture 2004-08, regular since 2025-05" is an old friend you see a lot of lately. Closeness is read from the "regular since" month, so pictures from before someone was in your life (a partner's childhood photos) don't make them a fixture of those years.

The scan reads metadata, not pictures. Your confirmations survive a rescan. Its guesses alone never make someone close family.

A named person the scan leaves out has fewer pictures than its floor: a tenth of your most-pictured person's count, between 5 and 25. [How the floor works](../make/cli/people.md#scan-and-inspect).

## What changes

Close family gets a place in the film when the period holds enough pictures of them. Their presence can make a busy day a bigger story, and an ordinary week worth keeping. A person film also uses the relationships you confirmed.

Set birth dates on people in Immich too. A birthday in the household or close family then gets a story of its own instead of disappearing into its week, and so does a visit from close family who don't live with you. [Days that get their own story](../how-it-chooses/moments-and-stories.md#days-that-get-their-own-story).

These settings apply to the next cut. Cut the same month again and compare it with the first one; you do not need to clear the preparation cache.

The [people registry reference](../reference/people-registry.md) has CLI editing, saved groups and account bindings. The exact family-seat thresholds are in the [configuration reference](../reference/config-reference.md).
