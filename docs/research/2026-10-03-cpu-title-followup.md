# CPU title and motion-report follow-up, 3 October 2026

This follows the [June hardware smoke](2026-10-03-june-hardware-smoke.md). Its accepted cold
runs and phase timings remain unchanged. The fixes start from main `acad2d8e3`.

## Keep the performance boundaries

Related changes: #1633 moved motion-description acquisition to explicit `prepare`; #1691
replaced per-frame CPU title rendering with two raster plates and FFmpeg fades; #1754 bounded
FFmpeg image and audio inputs. Those optimizations stay in place.

Normal film preparation reuses a rules draft. Its refinement does not consume motion sentences,
so acquiring them would add model calls and keyframe reads without improving that film. The fix
stops reporting this unrequested producer as missing. Basic, GPU and Full regressions require
zero motion-model calls. Explicit `prepare` still acquires descriptions, reuses warm entries and
reports real missing lines. This does **not** claim that the default films exercise motion captions.

On CPU, Pillow still draws the text once. FFmpeg applies the preset's entry scale/position and
opacity fades to a cropped transparent layer. The background stays still. Separate title/subtitle
timing, bokeh, fireworks and animated deblur remain GPU features; the native kernel probe still
protects processors that cannot execute the installed wheel. No dependency or Docker-image change
is required. Balanced output quality stays CRF 24.

## Controlled NAS comparison

Synology DS423+, Celeron J4125, existing shipping amd64 Docker image, 4 GiB limit, software
libx264, medium encoder preset, CRF 24, 1920×1080 at 60 fps, SDR. Each variant runs sequentially.
The baseline comes from `acad2d8e3`; the candidate changes only the CPU text animation path.
Both use the same installed dependencies, synthetic source, font, text and `fade_up` style.
These are two repeats on a shared NAS, not a claim about every title or an isolated CPU lab.

The source is FFmpeg `testsrc2=size=1920x1080:rate=60`, encoded for 0.5 seconds with libx264,
veryfast, CRF 24. `RenderingService` receives that clip for the opening and ending; its existing
static-frame extraction supplies the background. The third case uses the style's static gradient.
Opening/static duration is 3.5 seconds; ending duration is 7 seconds with a final white fade.
Text is `June 2023` / `A month of memories`, or `The end` for the ending. GPU title rendering
is disabled for both variants. Wall time includes extraction, rasterization and encoding;
the separate full-file decode check is excluded. Every output decoded successfully.

| Case | Baseline run 1 | Baseline run 2 | Text animation run 1 | Text animation run 2 |
| --- | ---: | ---: | ---: | ---: |
| Content-backed opening | 11.371 s | 11.936 s | 12.303 s | 11.385 s |
| Content-backed ending | 23.073 s | 29.154 s | 21.026 s | 24.216 s |
| Static gradient | 10.053 s | 13.135 s | 9.108 s | 8.950 s |

The opening's two-run average rose 0.191 seconds (1.6%); the ending and static case were faster.
That opening difference is within the observed run variation, not proof of zero overhead.

| Case | Baseline bytes | Text animation bytes | Extra bytes |
| --- | ---: | ---: | ---: |
| Opening | 167,174 | 194,925 | 27,751 |
| Ending | 432,946 | 445,687 | 12,741 |
| Static gradient | 62,738 | 97,081 | 34,343 |

The two repeats produced the same byte counts. Actual text motion costs more bytes than a fade;
the output quality setting did not change.

An earlier moving-background experiment was rejected: opening 18.476 seconds and ending
36.409 seconds versus baseline 11.371 and 23.073 seconds. No moving-background filter from that
experiment remains in the change.

## Verification boundary

Pixel tests cover slide and scale movement, one text rasterization per card, duration/frame count,
silent audio, fades, bounded inputs and 10-bit HLG/PQ output. Preparation tests retain explicit
motion acquisition and warm reuse, and require zero motion calls in ordinary films on all tiers.
The original matrix remains the cold end-to-end evidence; this follow-up checks the affected
rendering path separately and does not replace its timings.

## Saved June NAS cut

The accepted NAS Basic cut was rendered again in its original 4-CPU/4-GiB Docker environment
with Intel UHD 600 VAAPI. A copy of its database preserved the original run history; preparation
and selection were reused. Output stayed at 1080p60 SDR and balanced quality, with bundled music.
This was a render-phase check, not another cold run or clean-install measurement.

The render command completed in **487.521 seconds (8m 08s)**, followed by an independent complete
video/audio decode with exit 0. The original preparation, selection and cold-run timings were not
rewritten. Both files contain 3,572 video frames, lasting 59.533 seconds.

| Same-cut result | Original accepted film | CPU text animation |
| --- | ---: | ---: |
| Opening synthesis + encode, 3.5 s | 10.36 s | 6.63 s |
| Ending synthesis + encode, 4 s | 11.82 s | 7.31 s |
| Complete film bytes | 104,554,976 | 104,559,899 |

The complete film grew **4,923 bytes (0.0047%)**. These title log spans exclude content-frame
extraction and are single observations, separate from the two-repeat software benchmark above.
The existing one-frame source-clip underrun still appeared; this change does not address it.

The first render-check invocation stopped at CLI argument parsing after 9.646 seconds because
`--quality balanced` is not accepted by that command's legacy CLI choices. No rendering ran.
The successful invocation uses `output.quality: balanced` in its copied config and omits that
flag. Both receipts are retained, separately from the accepted original matrix.

Final local validation: 11,346 unit tests passed; 227 title integration tests passed; changed-line
coverage was 96%; documentation built with 119 sitemap pages. The first broad run inherited a
Makefile override that broke two launch-check command assertions; the complete coverage run
passed without that override. Privacy, type, lint, complexity and dependency gates passed.

The follow-up film was uploaded to the existing private comparison album. Hardware, Basic tier,
balanced quality, title-render patch digest and render-only status tags were read back and verified.
