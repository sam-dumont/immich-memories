---
title: Picking a shot
---

# Picking a shot

Within a moment, your favourite comes first. A big event is several moments: roughly one shot for every five distinct pictures of it, so a month with one real afternoon still makes a film. Without one, the editor looks for motion, recognisable people, good framing and a sharper picture. Near-identical frames compete for one place.

A selected video plays as video, usually up to six seconds. Clips shorter than two seconds are skipped.

The six seconds don't have to be the first six. Once the film's videos are picked, each one is read once for where to cut, and the answer is saved for every later film:

- **The picture.** It finds where the picture changes most, without decoding the whole clip. From a still camera that's the action: the riders crossing a finish line, not the empty road before them.
- **The sound.** A handheld clip changes everywhere, so its sound decides next: the loudest moment (the cheer when the candles go out, a squeal) with a second and a half of build-up before it. Without one, the stretch with the most talking wins. Only the sound is fetched, a minute of it at most, so a five-minute clip costs about what a one-minute one does.

A clip with nothing that stands out keeps its opening.

A short film lets a video play longer, up to twelve seconds, when it has content seconds unspent. A clip whose action sits at its very end grows backwards from the last frame.

Detected speech can extend the cut to a pause, up to twelve seconds. A run of "speech" longer than twelve seconds (a crowd, a PA, music) is no sentence and never stretches a cut. A pause means a full second of quiet: the breath between two people trading lines doesn't count, so a joke keeps its punchline and the laugh after it.

A Live Photo plays as motion when its clip moves and keeps its subject in view. Otherwise its still can remain in the film. See [Photos and Live Photos](../make/photos-and-live-photos.md).

A finger over the edge of the lens (a skin-toned, out-of-focus blob touching the border) is a warning, never a drop. The check runs on photos and on videos while the period is prepared. A flagged picture loses to a clean shot of the same moment, a flagged favourite still wins its moment, and a moment with only a flagged picture to show still gets shown. On a video it moves the cut, never the clip: when the picture decides where to cut, of two equally busy stretches the one with fewer flagged seconds plays. When the whole clip is flagged, the cut lands where it would have without the check.

It catches about half of real finger-over-the-lens shots, which is why it ranks rather than drops. It was trained on public pictures only; the maintainer's library was the test set, never the training set. The counts are in [Measure your setup](../better/measured.md#finger-over-the-lens).

Screenshots, documents and unusable frames normally stay out. For a film about objects, give it a curated album and a written subject: a loaf belongs in a film about making bread. A written subject requires a configured text reader; an album without a subject works with the rules reader.

The app tries to keep readable personal documents out: ID cards, boarding passes, bank cards,
letters and forms. It uses Immich's text recognition on every tier, plus descriptions when
available. Those checks can miss a document, especially when Immich has not recognised its text,
so review the cut before sharing. A favourite star does not override this check.
[Document checks and explicit choices](../reference/selection-internals/picking-shots.md#personal-documents)
has the exact rules.

If the wrong frame won, [swap or add it in the review](./overrule-it.md). The pool explains why each picture was kept or left out; the CLI has the same answer:

```bash
immich-memories runs why ASSET_ID
```

The exact ranking, scoring table, spacing and duplicate thresholds are in the [shot-selection reference](../reference/selection-internals/picking-shots.md).
