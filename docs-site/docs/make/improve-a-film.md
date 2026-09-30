---
title: Improve a film
description: Fix the cut, include the right people and change the length or presentation of your next film.
---

Start with the cut you can see. Open a picture to read why it stayed, then change what you disagree with. You do not need to configure a model to do this.

## Fix this cut

| You want to… | Do this |
|---|---|
| Remove a shot or trim a video | [Edit the reviewed cut](../how-it-chooses/overrule-it.md) |
| Replace a picture with another from the same moment | [Choose a replacement](../how-it-chooses/overrule-it.md) |
| Include someone important who is missing | Open **Pool**, find their picture and preview with it ticked. Undo **Never use** first if necessary. |
| Understand a missing or rejected picture | Open its explanation; [selection rules](../how-it-chooses/overview.md) explain the general idea |
| Change the titles, music or trip map | [Titles, maps and music](titles-maps-music.md) |
| Render a saved revision again | [Saved runs](cli/runs.md) |

Render the revision you reviewed. A new cut can choose differently; changing render options does not require a new selection.

## Improve the next cut

| The result | Check this |
|---|---|
| Faces are assigned to the wrong people | Correct the face recognition in Immich, then [confirm your people](../get-started/who-is-who.md) |
| Someone important gets too little room | Name their faces in Immich and [confirm their relationship](../get-started/who-is-who.md) |
| A trip is split or ordinary days look like travel | Set home and check the dates in [Memory types](memory-types.mdx) |
| The film is too long or unexpectedly short | [Length and filler](../how-it-chooses/length-and-filler.md) |
| Screenshots, shared pictures or repeats keep appearing | [Family, audience and duplicates](../how-it-chooses/family-audience-duplicates.md) |

The app works from dates, places, favourites and recognised people. Correct those in Immich when they are wrong: better source information helps more than another setting.

## Add more only when it helps

[Optional upgrades](../better/overview.md) explains what captions, a text reader and faster rendering add. Keep a film you like as a comparison, then change one thing at a time.

For exact thresholds and configuration keys, use [Selection internals](../reference/selection-internals/overview.md) and the [config reference](../reference/config-reference.md).
