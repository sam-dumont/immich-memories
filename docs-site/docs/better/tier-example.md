---
title: One month, two tiers
description: A real NAS and Full cut of the same CC0 fixture month, with films and limitations.
---

import Video from '@site/src/components/Video';

# One month, two tiers

These are two finished films from the same June 2024 fixture library: 133 assets and three synthetic people in a disposable Immich 3.2.2 instance. The pictures are [credited CC0 stock photographs](/demo/tier-fixture-credits.txt); the dates, names and household story are invented. No personal library was used. The identical bundled soundtrack, `calm_acoustic_1.opus`, is [MIT licensed](/demo/tier-music-license.txt).

Both requests asked for 60-second monthly highlights with photos, family sharing, template titles, and 720p SDR H.264 output. Upload was disabled. Each cut selects 14 shots and keeps four favourites. Thirteen shots overlap: NAS includes `IMG_2483.jpg`; Full instead includes `IMG_2432.jpg`. Full rejects three screen-like assets at eligibility; NAS rejects one.

## NAS

<Video src="/demo/tier-nas.mp4" poster="/demo/tier-nas-contact.png" controls playsInline width="100%" />

![Four actual frames from the NAS film: a playground swing, misty forest, market stall and mountain scenery.](/demo/tier-nas-contact.png)

## Full

<Video src="/demo/tier-full.mp4" poster="/demo/tier-full-contact.png" controls playsInline width="100%" />

![Four actual frames from the Full film: a playground swing, birthday cake, forest fern and mountain scenery.](/demo/tier-full-contact.png)

Full used real SmolVLM captions, detectors, the cached Laya checkpoint and the configured local `gemma-4-e4b-it-6bit` reader. Its preflight passed with 12 OK and four skipped checks. There was no reader or caption fallback.

| Recorded result | NAS | Full |
| --- | --- | --- |
| Finished duration | 56.000 seconds | 56.500 seconds |
| Selection wall time | 11.46 seconds | 42.70 seconds |
| Rendering wall time | 35.26 seconds | 35.49 seconds |
| File size | 36,879,073 bytes | 36,122,175 bytes |
| Video and audio | 1280×720 H.264, AAC | 1280×720 H.264, AAC |
| Complete decode check | Passed | Passed |

The duration is a target, not an exact output length. This is one paired example, not the [#1719 28-case suite](https://github.com/sam-dumont/immich-video-memory-generator/issues/1719), a quality guarantee or a speed benchmark. A changed cut is something you can watch, not proof that one tier always makes a better film.

## Limits of this run

Seven clips had no motion evidence, so Full used plain clip facts for them. Laya warned that checkpoint temperature `0.1006` for `choice:11+` was outside its supported range: it clamped the value, and that bucket's confidence is uncalibrated.

The store and cache started fresh and were shared between tiers. Full reused NAS facts and acquired its missing model facts. NAS selection used the existing environment (ONNX Runtime 1.28.0, Torch 2.14.0); Full selection and both renders used an isolated `all-mac` environment (ONNX Runtime 1.30.0, Torch 2.14.1, MLX 0.32.3 and laya-mlx 0.3.0). The machine was an Apple M5 Max; output encoding used software H.264. These differences and the shared warm cache rule out a fair speed comparison.

An initial NAS render failed because sandbox networking blocked localhost; the authorized retry succeeded. Its initial preflight also reported one missing configured path before generation. Both finished files passed `ffprobe` stream inspection and complete video/audio decoding with `ffmpeg`.

The [sanitized provenance](/demo/tier-provenance.json) records the exact source commit, cached model hashes, dependency versions, film SHA-256 hashes and selected filenames. The fixture credit manifest records each photograph's source, licence and shipped SHA-256. No credentials or raw execution logs are included.
