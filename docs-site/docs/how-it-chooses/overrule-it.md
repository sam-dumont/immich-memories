---
title: Edit the cut
---

import ThemedScreenshot from '@site/src/components/ThemedScreenshot';

# Edit the cut

Review a cut before rendering it. Changes to that cut become a saved revision; choices such as **Never use** apply to future films too.

## Remove, trim or swap

Open a shot in the contact sheet:

- **Remove from this cut** takes it out of this film.
- For a video, **Start here** and **End here** choose the interval to play. The preview loops the chosen interval; seek before or after it to move an edge outwards.
- Under **Other pictures of this moment**, choose a replacement and press **Use this picture instead**. **Keep the original** undoes a swap.

Press **Save revision**, then select that revision under **What to render**. The app renders those edits without choosing the shots again. **Undo** walks back an edit; **Discard changes** drops the unsaved changes.

## Tick and untick

Open **Pool** to see the pictures the cut considered. Tick a missing picture, untick one you do not want, then press **Preview with these choices**. This saves a revision in time order, with the length adjusted to your choices.

<ThemedScreenshot name="memory-pool-outcomes" alt="The Pool of a July cut: every picture it saw in the order they were taken, each with a tick box, its date, why it stayed out and Never use" />

A pool tick can include a picture held for family viewing: you have reviewed it yourself. An explicit tick also overrides **Never use** for this revision. The tile reminds you of that persistent decision; later automatic cuts still honour it.

To steer a new cut with the CLI, use `generate --include ASSET_ID` or `--exclude ASSET_ID`. New-cut inclusions still pass the sharing checks. [Exact inclusion rules](../reference/generation-contract.md).

## Star it in Immich

Favourite the pictures that matter before cutting. A favourite wins over other frames of its moment, but does not guarantee a place in every film: sharing and the available length still matter. [Exact favourite rules](../reference/selection-internals/picking-shots.md#favourite-guarantees).

## Pick who it's for

Set **Who may see it** in the brief, under **Length and pictures**:

<ThemedScreenshot name="memory-brief-sharing" alt="Length and pictures open in the brief: the length in minutes, Who may see it set to Just us with what that allows, and the photo and Live Photo boxes" />

| Audience | Use it for |
|---|---|
| **Just us** | The household, including private moments. |
| **Family** | Family viewing, with private moments kept out. The default is **As configured**, which uses `defaults.sharing` (Family unless changed). |
| **Shareable** | Wider sharing, with the strictest checks. |

Review the film before sending it. These checks can miss or misread a picture. [Sharing rules and limitations](../reference/selection-internals/family-audience-duplicates.md#sharing-levels).

## Your word on a picture

A held picture says why and offers **Clear hold**. Review the picture, then choose the audience allowed to see it. Clearing is per picture; the app does not clear holds on its own.

<ThemedScreenshot name="pictures-pool-held" alt="A pool tile held for family viewing: why it stayed out, Held: a nudity detector flagged it, then Never use and Clear hold" />

<ThemedScreenshot name="pictures-clear-dialog" alt="Clear this hold?: the held picture, why it was held, and which films may use it once you clear it" />

**Never use** excludes a picture from future automatic cuts; an explicit pool tick can still include it in a saved revision. **Undo** forgets either decision. To remove a picture from just one film, edit that cut instead.

<ThemedScreenshot name="pictures-pool-never-use" alt="A pool tile marked Never use: tick it to include it in this revision, or Undo" />

These decisions last across sessions and are shared by the UI and CLI. A Live Photo decision covers its clip too. [Picture decisions on the CLI](../make/cli/pictures.md) and [exact hold rules](../reference/selection-internals/family-audience-duplicates.md#your-word-on-a-picture).

## Tell it who's who

Correct wrongly recognised faces in Immich. In **Settings > People**, confirm your people and their relationships; only confirmed roles count. Set home so trips have a starting point. [People and home](../get-started/who-is-who.md) walks through this.

## Fine-tune selection

Start with favourites, confirmed roles and home before changing thresholds. For a result that still feels wrong, use [Improve a film](../make/improve-a-film.md). Exact family, burst and timing rules live in [Selection internals](../reference/selection-internals/overview.md).

## Read why

Every shot in the cut says why it's there. Open a picture's explanation in the contact sheet or pool for the full trail. The CLI gives the same reasoning, for the whole cut or one picture:

```bash
immich-memories runs story
immich-memories runs why ASSET_ID
```

[Saved runs](../make/cli/runs.md) explains how to inspect an earlier cut or render it again.
