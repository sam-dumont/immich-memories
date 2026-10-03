---
title: Picking a shot
---

# Picking a shot

Within a moment, your favourite comes first. Without one, the editor looks for motion, recognisable people, good framing and a sharper picture. Near-identical frames compete for one place.

A selected video plays as video, usually up to six seconds. Clips shorter than two seconds are skipped.

The six seconds don't have to be the first six. Every predicted frame in a video only stores what changed since the frames before it, so frame sizes go up when something crosses a still shot. Those sizes are in the file's index: the editor reads the index (around 64 KB, the same for a 12-second clip or a 5-minute one), never decodes a frame, and moves the cut to where the clip changes most. On a finish-line clip that means the riders crossing, not the empty road before them. A clip that is busy or quiet all the way through keeps its opening.

Detected speech can extend the cut to a pause, up to twelve seconds. A pause means a full second of quiet: the breath between two people trading lines doesn't count, so a joke keeps its punchline and the laugh after it.

A Live Photo plays as motion when its clip moves and keeps its subject in view. Otherwise its still can remain in the film. See [Photos and Live Photos](../make/photos-and-live-photos.md).

Screenshots, documents and unusable frames normally stay out. For a film about objects, give it a curated album and a written subject: a loaf belongs in a film about making bread. A written subject requires a configured text reader; an album without a subject works with the rules reader.

If the wrong frame won, [swap or add it in the review](./overrule-it.md). The pool explains why each picture was kept or left out; the CLI has the same answer:

```bash
immich-memories runs why ASSET_ID
```

The exact ranking, scoring table, spacing and duplicate thresholds are in the [shot-selection reference](../reference/selection-internals/picking-shots.md).
