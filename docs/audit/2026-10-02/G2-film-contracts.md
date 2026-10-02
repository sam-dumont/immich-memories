# G2 audit: film types and contracts (reference pages)

Paths are under `docs-site/docs/reference/` and `src/immich_memories/` unless stated. Line numbers are the page's own line numbers.

## 1. Coverage

| Page | Claims checked (approx.) | Findings | Verdict |
|---|---|---|---|
| film-types.mdx | ~110 | 7 | Mostly accurate. Wrong on what a trip film keeps, and the "three days = 20 s" example contradicts its own rule |
| generation-contract.md | ~60 | 4 | Accurate except the special_day refusal list, the NAS 1080p cap, and trip/album file names |
| preparation.md | ~25 | 0 | Accurate. The example table's numbers are internally consistent (0.948 s x 10,000 = 2 h 38 min; shares and elapsed times check out) |
| people-registry.md | ~35 | 1 | Accurate. The tier table leaves out the household-child rule |
| special-days.md | ~45 | 2 | Accurate. Missing `--also-skip`, and the holiday wording disagrees with `discover-days --help` |
| output-rendering.md | ~90 | 3 | Accurate on numbers. Named styles cannot be chosen through config; the ending colour is configurable |
| media-processing.md | ~60 | 2 | HDR end to end is wrong for the default config (H.264). The worked Live Photo merge table is arithmetically wrong |
| sentence-parser.md | ~30 | 0 | Spot-checked constants match (thin < 12, generic heads, 10th-percentile sharpness, 35 pictures, pinned WordNet). Several numbers could not be checked (list below) |

Checked and correct (abbreviated evidence): the 10 memory types match `generate --help` and `memory_types/registry.py:OFFERED_MEMORY_TYPES`. Length targets match `planning/memory_length.py` (`_recap_duration_from_date_range` gives 60 s/month capped at 600; a season is 195 s; on_this_day 45; monthly 60) and `planning/auto_duration.py` (`_TRIP_*` 30+10/day within 60-300; `_SPECIAL_DAY_*` 30+6/h within 60-180; `SPECIAL_DAY_MIN_CONTENT_SECONDS`=30; `_MAX_DIVERSE_SECONDS_PER_DAY`=30; the four `DURATION_FROM_*` strings). The episode gap is 90 min (`analysis/moment_grouping.py:EPISODE_WINDOW_MINUTES`), and AND binds before OR (`api/person_expression.py:205`). Grouped-condition refusals: `cli/generate_resolution.py:165`. Birthday: `BIRTHDAY_HISTORY_YEARS`=5, `BIRTHDAY_MEMORY_SECONDS`=600, the window starts the day after (`timeperiod.birthday_year`), and 29 Feb falls on the 28th. Holiday: window ±2 days, years_back 5, `_FIXED_HOLIDAYS`, `_MOTHERS_DAY`/`_FATHERS_DAY` match the country table row for row, `_FAMILY_DAYS`, and US without a home base (`home_country._WITHOUT_A_HOME`). Trip defaults are 50/2/2 (`config_models_automation.TripsConfig`); the gap is `>` and the distance `>=` (`analysis/trip_detection.py`); the window runs Dec 1 to Jan 31 (`analysis/trip_discovery.py`); naming uses `COVERING_SHARE`=0.85 and `DOMINANT_CITY_SHARE`=0.5. Album: the conflict list matches `_validate_album_scope`, the file is `album_<slug>`, and `max_album_assets`=10000, newest first. Special days: 5-h split (`_NIGHT_GAP_HOURS`), `_LONGEST_RUN_HOURS`=48, the NAS loud facts (3 favourites, 3 videos and ≥50 %, 20 pictures/6 h with family, ranking order), `special_days_per_year`=6, `WINDOW_DAYS`=3, roundness ladder, the evidence text and "via" line (`cli/auto_cmd.py:40`), vocabulary 10 / 3 % / 2 words / 34 days, crowd 4 within 15 days, `MIN_FILM_SECONDS`=30, `_MIN_WINDOW_SHARE`=0.5, `_ONE_SAVE`=3. Titles: 3.5 s, the 2 s ending floor (`_MIN_ENDING_SECONDS`), 80 % height (`safe_zones._VERTICAL`), divider rule (`filename_builder.get_divider_mode`, first changes win: `title_divider_planner.py:225`), location cards 30 km / 50 km (`location_card_route.py`), map moves 6/8 s on a log scale over 30-3000 km plus a 2 s hold (`processing/map_move_timing.py`), ~150 renders, ArcGIS host, fast preset, 360-px plates. Mood-to-palette and style palettes match `titles/styles.py`. Fonts 3.79 MB + 39.5 MB (summed pinned sizes). Captions 48 px (`_FONT_RATIO` 0.0444 x 1080), opacity 0.85, familiar places 250 m and 7 days. Run summary labels **Title From** / **Timeline** (`cli/runs.py:91-98`), `run.timeline` (`tracking/report.py:253`), TitleSource values. Music: 28 bundled tracks in 5 moods, 29.5-32.7 s (ffprobe), beat tolerance 0.2, volume -20+20v dB (`generate_music.py:437`), `local_music_dir` ~/Music/Memories. Ken Burns zoom 5-12 % seeded by asset id, largest face. Live Photos: 10 s / 3.5 s / residual 1.5 over 12 frames / 6 s cap (`editorial_structure_budget.MOTION_CAP_SECONDS`), Pixel 1.5 vs 3.0, 48 kHz, STFT 1024/256 (5.3 ms), 20-frame template, 30 ms fade, `BURST_CRF`=18. Gain-map tags 0x0021/0x0030, `exiftool` fallback, formula (`photos/animator.py:450`). `hdr` + H.264/ProRes refused (`encoding_plan._validate_codec_policy`). Reader drops: 3 retries at 2 then 4 s (`analysis/llm_query.py:103`). Defaults: `defaults.sharing` family, add_date/add_place on, `output.resolution` 1080p, `output.directory` ~/Videos/Memories, 8-char recipe hash. Delivery removes the local output (`generate_delivery._cleanup_local_output`). `IMMICH_MEMORIES_OWNER` (`cli/people_cmd.py:101`). Owner ladder told/account/inferred (`people/graph.py:126`). Tiers 24 months / 3 years / 0.35, 12, ≤4 months at ≥20 (`people/signatures.py`). Account-name regex (`config_models.py:73`). All relative links and anchors in the 8 pages resolve. No em dashes or chatbot words found in the 8 pages.

## 2. Findings

### G2-1 [WRONG] media-processing.md:169, :184 — "A film keeps the dynamic range its sources have" is false on the default config
- **Claim:** "A film keeps the dynamic range its sources have. HDR video (HLG or PQ) stays HDR" (169). "`output.hdr_mode` is `auto` (HDR when any selected source is HDR)" (184).
- **Reality:** HDR output needs codec H.265. The default `output.codec` is `h264` (`config_models_render.py:100`). Under `auto` + H.264, HDR sources are tone-mapped to SDR (`processing/encoding_plan.py:316-338`: `hdr = codec is H265 and (...)`; `tone_map_to_sdr = has_hdr_input and not hdr`). `_codec_for_available_hardware` never upgrades H.264 to H.265.
- **Evidence:** `uv run --no-sync python -c` resolving `EncodingRequest(codec=OutputConfig().codec, hdr_mode=AUTO, ...)` with HDR (HLG) input printed `h264 auto` / `h264 False True none`, meaning hdr=False and tone_map_to_sdr=True.
- **Cross-page:** this contradicts `reference/config-reference.md:293-296`, which is correct ("with `codec: h264`, `auto` tone-maps detected HDR sources"), and `run/reference/configuration.md:184-185`.
- **Fix:** "With `output.codec: h265` (or `--format h265`), a film keeps the dynamic range... The default `h264` is SDR: `auto` tone-maps HDR sources." Same for line 184.
- **Confidence:** VERIFIED.

### G2-2 [WRONG] film-types.mdx:269-271 — a trip film does not "take everything shot in the trip's window"
- **Claim:** "`--person` narrows detection ...; the film still takes everything shot in the trip's window."
- **Reality:** Videos are fetched by date. Photos are fetched by date and then filtered to geotagged ones at least `min_distance_km` from home (`cli/_trip_generation.py:36-58` `_filter_photos_near_trip`, applied at :190). Photos with no GPS, and photos within 50 km of home, are dropped from the trip film. The log says "dropped N (no GPS or near home)".
- **Fix:** "...the film takes every video in the trip's window and every photo there that carries GPS at least `min_distance_km` from home."
- **Confidence:** VERIFIED (code read, not executed).

### G2-3 [WRONG] generation-contract.md:116 (also film-types.mdx:351) — special_day refuses more than "only without `--day`"
- **Claim:** "`special_day` works on any day ... and refuses only without `--day`."
- **Reality:** It also refuses when the day holds more than one catalogued event and no `--event-id` is given ("... has multiple catalogued events; choose one with --event-id"), and when `--event-id` matches nothing (`cli/generate_resolution.py:96-111` `_catalogued_event`). `--event-id` appears nowhere on either page.
- **Fix:** Add "A day with two catalogued occasions needs `--event-id` (listed by `days-due`/`days-export`)." Change "refuses only" accordingly.
- **Confidence:** VERIFIED (code read).

### G2-4 [WRONG] media-processing.md:147-153 — the worked merge table's durations do not add up
- **Claim:** For shutters at 0, 0.5 and 2 s (3 s clips), Photo 2 plays to 1.25 s for "~1.5 s" and Photo 3 plays to the end for "~1.5 s".
- **Reality:** Using the documented rule (cut at the midpoint between shutters; `processing/live_photo_merger.py:543-563` `_gap_aware_trims`; clip i covers shutter_i ± 1.5 s): Photo 1 plays -1.5 to 0.25 = 1.75 s. Photo 2 plays 0.25 to 1.25 = **1.0 s**. Photo 3 plays 1.25 to 3.5 = **2.25 s**. Total 5.0 s, which equals the continuous span -1.5 to 3.5. The table sums to 4.75 s, which cannot be continuous. "Photo 2 | shutter-centred start" is also really the 0.25 s midpoint.
- **Fix:** Durations ~1.75 / ~1.0 / ~2.25 s. Start column: start / 0.25 s / 1.25 s.
- **Confidence:** VERIFIED by arithmetic against code (not executed on media).

### G2-5 [WRONG] film-types.mdx:31-33 — "capped at 30 s a day, so a month with three photographed days gets about 20 s"
- **Claim:** The 30 s/day cap yields ~20 s for a three-day month.
- **Reality:** `_Material.diverse_capacity_seconds` (`planning/auto_duration.py:143-158`) caps each day at 30 s and adds title + ending time. Three full days can therefore support up to 90 s + titles, and the monthly 60 s target then binds. ~20 s happens only if those days are thin (e.g. a couple of stills). The "so" does not follow from the rule stated. `how-it-chooses/length-and-filler.md:7` says "might make twenty seconds", which is the safe form.
- **Fix:** "...so a month with three thinly photographed days can land near 20 s, not a minute."
- **Confidence:** VERIFIED (code). The exact output for any given library is not executed.

### G2-6 [GAP] output-rendering.md:41-51 — the five named styles cannot be selected through config
- **Claim:** A table of `modern_warm` ... `soft_romantic`. "`style_mode: random` picks a named style."
- **Reality:** `title_screens.style_mode` is `Literal["auto","random"]` (`config_models_render.py:293`). Writing `style_mode: elegant_minimal` fails validation. The names can only be used with `titles test --style` (`titles test --help`). The generator's named-style branch (`titles/generator.py:167`) is unreachable from config. `auto` with no mood also picks a random named style (`generator.py:171`).
- **Fix:** State that the names are previews for `titles test --style` and the pool `random` draws from, and that a film cannot be pinned to one.
- **Confidence:** VERIFIED (schema read; config load not executed).

### G2-7 [GAP] generation-contract.md:27-28 — NAS tier caps output at 1080p
- **Claim:** "`auto` matches source clips ... `output.resolution`, 1080p by default."
- **Reality:** `processing/output_canvas.py:resolve_generation_canvas` caps any canvas above 1920x1080 to 1080p when `config.tier == "nas"`, and logs it. A NAS user passing `--resolution 4k` or `auto` on 4K sources gets 1080p. Already stated in `run/reference/configuration.md:185` ("NAS output remains capped at 1080p"), but not here.
- **Fix:** Add one sentence and link to the tier page.
- **Confidence:** VERIFIED (code read).

### G2-8 [GAP] film-types.mdx:340 vs special-days.md:26 — the config key is written two ways
- **Claim:** film-types writes `automation.special_days_per_year (6)`. special-days writes `advanced.automation.special_days_per_year`.
- **Reality:** `automation` is a Tier-2 section (`_TIER2_SECTIONS`), so the YAML key is `advanced.automation.special_days_per_year`. A reader copying film-types' key writes it at the top level.
- **Fix:** Use `advanced.automation.special_days_per_year` in film-types.
- **Confidence:** LIKELY (did not load a YAML with the top-level form to see whether it is rejected or ignored).

### G2-9 [GAP] special-days.md:13-21 — `discover-days --also-skip` is undocumented, and the holiday rule disagrees with `--help`
- **Reality:** `discover-days --help` lists `--also-skip HOLIDAY  A holiday name or MM-DD this library keeps that the defaults miss`. The page never mentions it. The help also says holidays are skipped outright ("and so are holidays"), while the page (17-21) says a reader asks whether the occasion was the holiday itself, and `analysis/special_day_holiday.py` exists. One of the two surfaces is stale. The page agrees with the code that exists.
- **Fix:** Document `--also-skip`. Ask the CLI owner to update the help text, or note the NAS-only skip there.
- **Confidence:** VERIFIED (help output). Which surface is current is LIKELY (reader path not executed).

### G2-10 [GAP] people-registry.md:14-17 — the tier table leaves out the household-child rule, and "each" should be an average
- **Reality:** `people/signatures.py:classify` puts a person into `inner` when `is_household_child` holds: first seen within 1 year of the birth date and continuity ≥ 0.5 (`_HOUSEHOLD_CHILD_MIN_CONTINUITY`). This applies whatever their month count, so a toddler with 10 active months is `inner`, against the table. `event` is `month_count <= 4 and concentration >= 20` (pictures per active month on average), not "twenty-plus pictures each".
- **Fix:** Add a row or footnote for children born into the library. Say "averaging twenty or more pictures a month".
- **Confidence:** VERIFIED (code read).

### G2-11 [GAP] film-types.mdx:262-267 — trip selection details are missing
- **Reality:** `--trip-index` is 1-based (`cli/_trip_display.py:58-71`). `--month M` also picks a trip, the one whose midpoint is nearest the 15th (`generate --help`: "selects trip by month"; `_trip_display.py:79-85`). Trip film names are `trip_<place>_<start>.mp4` (`cli/_trip_generation.py:trip_output_path`). generation-contract.md:220-221 gives only the `{people}_{memory-type}_{dates}_{hash}` pattern, which does not hold for trips or albums.
- **Fix:** One line each.
- **Confidence:** VERIFIED (code read).

### G2-12 [CLARITY] film-types.mdx:83 — month dividers also need a single calendar year
- **Claim:** "Month dividers appear only when the range spans four months or more."
- **Reality:** `filename_builder.get_divider_mode`: ≤3 months gives none, a range crossing years gives **year** dividers, and only a single year of 4+ months gives month dividers. output-rendering.md:13 states it correctly ("single-year film"). A birthday year (July to July) gets year cards, not month cards, which surprises a reader of film-types.
- **Fix:** "...spans four months or more inside one calendar year; a range across years gets year cards."
- **Confidence:** VERIFIED.

### G2-13 [CLARITY] film-types.mdx:154, :173-183 — On this day and holiday limits
- "Every earlier year" on this day: without `--years-back` it is capped at 30 years (`date_builders.build_on_this_day`, `effective_years_back = 30`). The web or factory default is 5 (`factory._on_this_day years_back=5`), so the CLI and preset defaults differ and neither is stated.
- `thanksgiving` "where the country's public calendar has it" is correct, but the reader is not told the failure mode. Outside the US it raises ``'thanksgiving' is not kept in CA`` even for Canada, because the `holidays` library lists Canadian Thanksgiving as non-national (run: `resolve_holiday('thanksgiving',2025,country='CA')` gives ERR; `holidays.country_holidays('CA',years=2025)` has no Thanksgiving). Suggest "else use `MM-DD`".
- **Confidence:** VERIFIED.

### G2-14 [CLARITY] output-rendering.md:23 — the ending is not always white
- **Claim:** "Ending: a fade to white, no text."
- **Reality:** `title_screens.fade_color` (white|black, default white; `config_models_render.py:287`) and `generate --fade-color` set it.
- **Fix:** "a fade to white (`title_screens.fade_color`, or `--fade-color black`)".
- **Confidence:** VERIFIED.

### G2-15 [CLARITY] generation-contract.md:108 — "Albums and trips read the primary only"
- **Reality:** Passing `--accounts` with an album or trip is a usage error (`cli/run_people.py:62-63`: "--accounts reads date-range memories, not albums or trips"). It is not silently narrowed. A reader expecting a quiet fallback gets an error.
- **Fix:** "Albums and trips refuse `--accounts`; they read the primary."
- **Confidence:** VERIFIED.

### G2-16 [POLISH] output-rendering.md:43 — `modern_warm` "Bold, semibold"
- `PRESET_STYLES["modern_warm"].font_weight="semibold"` (`titles/styles.py:268-278`). Nothing is bold.
- **Confidence:** VERIFIED.

## 3. Unverifiable claims (not reported as wrong)
- film-types.mdx:237 "a lake 590 km from the test home"; trip naming examples (Crete, Mallorca), whose outcome depends on Immich geodata.
- film-types.mdx:143 the exact log line `history: 2 of 5 earlier windows hold material` (string not located; did not grep exhaustively).
- generation-contract.md:103 "An id nothing holds stops the run before it reads a picture" (not traced end to end).
- generation-contract.md:226-228 the timeline filing rule (timezone majority), not traced in `delivery_timestamp.py`.
- media-processing.md:167/171 demo durations 4.5 s and 8.1 s; "a lone clip runs 1.7 to 3.3 s"; "three shots in 1.4 s can stitch to 2.4 s"; "At 1.5 or above something happened in every burst we measured".
- media-processing.md:220 NAS Live merge bound 1920x1080 (consistent with make/photos-and-live-photos.md:45, not traced).
- special-days.md:62 "2,368 such copies in 21,520 files"; :54-55 "fifty-five new beginnings".
- sentence-parser.md:27 WordNet "11 MB"; :147 "one search call per 1,000 pictures"; :176 "7 to 46 seconds"; the sample trace counts.
- output-rendering.md:196 ">1000 tiles per map"; "None of the ducking constants is a config key" (spot-checked, not exhaustive).
- preparation.md example timings (illustrative; internally consistent).
