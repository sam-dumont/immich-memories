---
title: Picking a shot
---

# Picking a shot

Within a moment, your favourite comes first. Without one, the editor looks for motion, recognisable people, good framing and a sharper picture. Near-identical frames compete for one place.

A selected video plays as video, usually up to six seconds. Detected speech can extend the cut to a pause, up to twelve seconds. Clips shorter than two seconds are skipped.

A Live Photo plays as motion when its clip moves and keeps its subject in view. Otherwise its still can remain in the film. See [Photos and Live Photos](../make/photos-and-live-photos.md).

Screenshots, documents and unusable frames normally stay out. For a film about objects, give it a curated album and a written subject: a loaf belongs in a film about making bread. A written subject requires a configured text reader; an album without a subject works with the rules reader.

If the wrong frame won, [swap or add it in the review](./overrule-it.md). The pool explains why each picture was kept or left out; the CLI has the same answer:

```bash
immich-memories runs why ASSET_ID
```

The exact ranking, scoring table, spacing and duplicate thresholds are in the [shot-selection reference](../reference/selection-internals/picking-shots.md).
