---
title: pictures
---

# pictures

Set a persistent decision on one picture: clear a sharing hold or never use it. These commands write the same decisions as the browser pool's **Clear hold**, **Never use** and **Undo** buttons.

In Docker, run these commands from the installation folder with
`docker compose exec immich-memories` before `immich-memories`.

Open the picture in Immich and copy the ID from the end of its URL: `/photos/ASSET_ID`. Replace `ASSET_ID` below with that ID.

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

**Never use** excludes the picture from future automatic selections. Undo it to allow automatic
selection again; an explicit pool tick can still include it in one saved revision. `undo` also
removes a clearance, letting the app's normal holds apply again.

A Live Photo decision covers its still and motion clip. To change only this film, use a saved review revision instead: [Review and adjust](../../how-it-chooses/overrule-it.md).

Every flag: [CLI reference](../../reference/cli-reference.md#pictures).
