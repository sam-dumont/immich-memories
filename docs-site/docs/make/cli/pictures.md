---
title: pictures
---

# pictures

Set a persistent decision on one picture: clear a sharing hold or never use it. These commands write the same decisions as the browser pool's **Clear hold**, **Never use** and **Undo** buttons.

Use the asset ID shown by Immich or `runs why`, replacing `ASSET_ID` below.

## Inspect a hold

```bash
immich-memories pictures show ASSET_ID
```

Example output:

```text
Held: a nudity detector flagged it.
```

## Clear a hold

```bash
immich-memories pictures clear-hold ASSET_ID
```

The command names the hold and asks which films may use the picture: `anyone`, `family` or `just-us`. It then asks for confirmation.

For a scripted decision:

```bash
immich-memories pictures clear-hold ASSET_ID --level just-us --yes
```

Clearance persists until undone. It does not change what kind of media the picture is: clearing a hold on a screenshot does not make it ordinary footage.

## Never use, or undo

```bash
immich-memories pictures never-use ASSET_ID
immich-memories pictures undo ASSET_ID
immich-memories pictures list
```

**Never use** excludes the picture from future cuts. Undo that decision before including it again. `undo` also removes a clearance, letting the app's normal holds apply again.

A Live Photo decision covers its still and motion clip. To change only this film, use a saved review revision instead: [Review and adjust](../../how-it-chooses/overrule-it.md).

Every flag: [CLI reference](../../reference/cli-reference.md#pictures).
