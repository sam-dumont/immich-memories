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

A photographed ID card, passport, bank card, letter, form or event voucher with readable personal text is excluded on every tier. A caption naming the document catches it on Full, and holds the shot outright: a family holding boarding passes in an ordinary photo is held too, because losing that shot beats shipping one that reads. Everywhere else it's Immich's own OCR, and there the frame head matters: a personal-record field label (date of birth, national number, and their equivalents across a dozen languages and scripts), the document's own title word, a passport's machine-readable zone, a card or IBAN number that passes its own check digit, or a gift voucher naming who it's for, counts on a frame the head calls a document or a record, or hasn't read at all; it does not count on a frame the head already calls something else, like an ordinary scene or a person. A generic ski, bus or day pass is not a document; a boarding pass still is, since it carries the traveller's name. An ordinary scene with a sign or a programme in it stays in. OCR comes from Immich's own server (2.2 and up), read through a cheap keyword search first so the full per-picture read only runs on the few pictures worth it, plus a direct read for any picture the frame head already calls a document (an MRZ line or a card number can't be found by a keyword search); on an older server, or if a read fails, that signal is just off for the run and every other check still applies. The only exemption is a picture passed with `generate --include`: a favourite star is not the same as you choosing to ship a readable document.

If the wrong frame won, [swap or add it in the review](./overrule-it.md). The pool explains why each picture was kept or left out; the CLI has the same answer:

```bash
immich-memories runs why ASSET_ID
```

The exact ranking, scoring table, spacing and duplicate thresholds are in the [shot-selection reference](../reference/selection-internals/picking-shots.md).
