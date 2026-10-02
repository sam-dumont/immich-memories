# G1 audit: config-reference, FAQ, troubleshooting, web-ui-details

Auditor G1. Repo at `/home/user/immich-video-memory-generator`, read-only; `git status` was clean before and after.
Tools I ran: a schema dump script (`scratchpad/dump.py`, which walks `Config.model_fields` recursively), a mechanical diff of the doc's YAML blocks against the schema (`scratchpad/diff.py`), `Config.from_yaml(...)` probes run with an empty HOME and env, `make docs-config-check` (it passes), CLI `--help`, and grep over `src/` and `web/src/`.

## 1. Coverage

| Page | Claims checked (approx.) | Findings | Verdict |
|---|---|---|---|
| reference/config-reference.md (979 lines) | ~420: 209 schema keys (defaults, types, ranges, choices), ~120 behaviour sentences, 20 CLI/env references, every relative link and anchor | 21 | Defaults are very accurate. Mechanically, no real default mismatches. A few behaviour sentences are wrong (`ultra`, `title_llm`, `thinking`, server host, compose hostname). Placement guidance is inconsistent. |
| reference/faq.md (79 lines) | ~30 | 3 | Accurate. Small clarity issues. |
| reference/troubleshooting.md (159 lines) | ~45 (18 quoted strings grepped) | 4 | All quoted errors exist except an FFmpeg-native one, which is expected. One heading describes a failure the code now prevents. |
| reference/web-ui-details.md (82 lines) | ~40 UI labels, routes and behaviours | 1 | Every label I checked exists verbatim in `web/src`. Accurate. |
| examples/config.example.yaml (linked from run/config-file.md:107) | validated, plus every key | 1 (bundled) | Validates, but carries a dead key, retired values, a stale head count and a dead path. |

Every relative link and anchor on the 4 pages resolves (script check).

## 2. Findings

### G1-1 [WRONG] config-reference.md:279: `ultra` is not a quality value
- **Claim:** "Choose `balanced`, `high`, `ultra` or `fast` for a new configuration."
- **Reality:** `output.quality` is `Literal['high','balanced','fast']`. `ultra` fails validation at startup. The table just above (271-275) has no `ultra` row, and line 277 says "There is no tier below `balanced`".
- **Evidence:** `src/immich_memories/config_models_render.py:93`. Running `OutputConfig(quality='ultra')` gives `Input should be 'high', 'balanced' or 'fast'`. `_QUALITY_CRF` in `processing/hdr_utilities.py:358` has no `ultra`.
- **Fix:** "Choose `balanced`, `high` or `fast`."
- **Confidence:** VERIFIED.

### G1-2 [WRONG] config-reference.md:527,534-536: `title_llm.model` does not default to empty
- **Claim:** "`model: "llama3.2"  # example; the default is empty, which means "use llm"`". Also: "When `title_llm.model` is empty, `llm` is used."
- **Reality:** `title_llm` is an `LLMConfig`, and `LLMConfig.model` defaults to `gemma-4-E4B-it-Q4_0`. So a `title_llm:` block without `model` is never empty and is always used (`titles/film_title.py:94`: `config.title_llm if config.title_llm and config.title_llm.model else config.llm`). There are two consequences:
  - A block with `base_url` but no `model` is auto-enabled and asks that server for `gemma-4-E4B-it-Q4_0`.
  - A block with neither `base_url` nor `model` (only `timeout_seconds`, say) has `enabled: False`. Titles then get no LLM at all, even when `llm` is configured.
  
  Only an explicit `model: ""` falls back to `llm`.
- **Evidence:** `LLMConfig.model_validate({'provider':'openai-compatible','timeout_seconds':300})` gives `enabled False, model 'gemma-4-E4B-it-Q4_0'`. `{'base_url':'http://localhost:8080/v1'}` gives `enabled True, model 'gemma-4-E4B-it-Q4_0'`.
- **Fix:** Document that the switch is "the whole block, when present". Say a partial block silently disables or redirects titles. Or fix the code so it falls back when `model` is not in `model_fields_set`.
- **Confidence:** VERIFIED (validator run). The end-to-end title call was not executed.

### G1-3 [WRONG] config-reference.md:851-853 (and 874): an explicit `host: "0.0.0.0"` in config.yaml is ignored
- **Claim:** The block shows `host: "0.0.0.0"  # Listen address. Without auth and without this set explicitly, the UI binds 127.0.0.1`. This implies that writing it explicitly binds the LAN.
- **Reality:** The loader deletes a file-sourced `server.host: 0.0.0.0` (#507, "it does not count as a choice") and warns. With auth off, the UI binds 127.0.0.1. A NAS newcomer who copies the block gets a UI they cannot reach from the LAN. Any other address, the env var `IMMICH_MEMORIES_SERVER__HOST`, or `--host` does count.
- **Evidence:** `config_loader.py:171-191` (`_drop_app_written_wildcard_host`). A probe with `server: {host: "0.0.0.0"}` logs "Ignoring 'server.host: 0.0.0.0' …", and `effective_host(auth_enabled=False)` returns `127.0.0.1`.
- **Fix:** Show `host` as unset or commented in the block. State that `0.0.0.0` in the file is ignored. Point at `allow_unauthenticated_lan: true`, auth, `--host`, or `IMMICH_MEMORIES_SERVER__HOST`.
- **Confidence:** VERIFIED.

### G1-4 [WRONG] config-reference.md:703: wrong inference hostname for the compose profile
- **Claim:** "(`http://inference:8092` in the compose profile)".
- **Reality:** The compose service and container are `immich-memories-inference`. The compose comment, better/inference.md:46, better/captions.md:35 and caption-service.md:145 all use `http://immich-memories-inference:8092`. `http://inference:8092` is the Kubernetes name (run/kubernetes.md:142). With the default `fallback_to_local: true`, a wrong host silently runs everything in-process. With it off, config load fails (see G1-5).
- **Evidence:** `docker-compose.yml:86,153,155`.
- **Fix:** Write "`http://immich-memories-inference:8092` in the compose profile, `http://inference:8092` in the Kubernetes manifests".
- **Confidence:** VERIFIED.

### G1-5 [GAP] config-reference.md:720-723: with `fallback_to_local: false`, an unreachable service breaks config load
- **Claim:** "With it off, the cut refuses until the service is back."
- **Reality:** With `tier: auto` (the default), `apply_tier` probes `GET {facts_base_url}/health` while the Config is being built. If that probe fails and `fallback_to_local` is false, the Config raises `ValidationError: Cannot verify the required inference service's compute`. So every command fails, not only the cut, and that includes `config show`, `preflight` and `ui`. The probe also runs on every config load (2 s timeout), which the page does not mention.
- **Evidence:** `config_compute.py:13-31` and `config_tiers.py:68-71`. Probe with `facts_base_url: http://127.0.0.1:59999, fallback_to_local: false` gives `ERR ValidationError ... Cannot verify the required inference service's compute`.
- **Fix:** Document it, or pin `tier:` explicitly to avoid the probe.
- **Confidence:** VERIFIED.

### G1-6 [WRONG] config-reference.md:442-444: `thinking` affects one call, not two
- **Claim:** "`low`, `high` and `max` run the model in reasoning mode for two calls: title generation, and the special-day question in `discover-days`."
- **Reality:** Only title generation passes `thinking=True` (`titles/llm_titles.py:764`). The special-day question explicitly passes `thinking=False` on both paths (`analysis/special_day.py:798,806`). The comment at 787-794 explains why: asking it to think starves the 4000-token answer. A repo-wide grep finds no other `thinking=True` call site.
- **Evidence:** the greps above. `llm_query.py:251,329` gates reasoning on `thinking and llm_config.reasons`.
- **Fix:** "…in reasoning mode for one call: title generation."
- **Confidence:** LIKELY. Static analysis only; no request was sent.

### G1-7 [WRONG] config-reference.md:26-27: wrong merge rule for the two placements
- **Claim:** "Both placements are read; if a section appears in both, the top-level one wins."
- **Reality:** The two are deep-merged key by key, at every depth (#765), and the top level wins only a tie. The page's wording implies the whole `advanced.<section>` block is discarded. run/config-file.md:121 ("merge key by key; a top-level key wins a tie") and run/reference/configuration.md:85-88 state it correctly, so the pages contradict each other.
- **Evidence:** `config_loader.py:194-232` (`_deep_merge`).
- **Fix:** Use the configuration.md wording.
- **Confidence:** VERIFIED.

### G1-8 [WRONG] config-reference.md:14-15: Tier-2 list omits `speech`
- **Claim:** The tip lists 13 Tier-2 sections and leaves out `speech`.
- **Reality:** `_TIER2_SECTIONS` holds 14 sections, `speech` included. The page itself shows `advanced: speech:` (line 206), and run/reference/configuration.md:85 includes `speech`. The `Config` docstring (`config_loader.py:297-299`) and CLAUDE.md also omit it, so this is code-adjacent drift.
- **Evidence:** `config_loader.py:58-75`.
- **Fix:** Add `speech`.
- **Confidence:** VERIFIED.

### G1-9 [CLARITY] config-reference.md, whole page: Tier-2 sections are shown at top level with no `advanced:`
- **Claim:** The tip says Tier-2 sections "go under an `advanced:` key". Then `analysis` (166), `hardware` (326), `musicgen`/`ace_step` (353-372, in the same block as Tier-1 `audio:`), `llm` (406, 482, 497), `triage` (541), `editorial` (556), `server` (851), `auth` (925), `automation` (893) and `notifications` (962) are all printed at top level.
- **Reality:** Only `speech`, `inference` and `free_text` are wrapped. Some sections get a "place under `advanced:`" sentence (editorial, automation, auth, notifications). `analysis`, `hardware`, `llm`, `musicgen`, `ace_step`, `triage` and `server` get none. Both placements load, so nothing breaks. But a newcomer who copies a block cannot tell which convention the page wants, and `config show` reports the key the way it was written.
- **Fix:** Wrap every Tier-2 example in `advanced:`, or add one consistent note per section.
- **Confidence:** VERIFIED.

### G1-10 [WRONG] config-reference.md:334: `hardware.enabled: false` is not the only way to force CPU
- **Claim:** "`hardware.enabled: false` is the only way to force CPU."
- **Reality:** `backend: "none"` is an allowed value (the page's own line 328 lists it). With it, no detector matches, `detect_hardware_acceleration` returns `HWAccelBackend.NONE` and the render encodes in software. One difference remains: clip extraction (`processing/clips.py:44-47,394`) calls `detect_hardware_acceleration()` with `auto`, whatever `backend` says. So `backend: none` does not keep clip extraction off the GPU, while `enabled: false` does.
- **Evidence:** `processing/hardware_detection.py:301-331` and `processing/clips.py:44-47`.
- **Fix:** "`hardware.enabled: false` is the only setting that keeps every stage on the CPU; `backend: none` forces a software render encode but clip extraction still probes." Or fix clips.py to honour `backend`.
- **Confidence:** LIKELY. Static read; no encode was run.

### G1-11 [CLARITY] config-reference.md:339: the burst merge does honour `backend`; clip extraction does not
- **Claim:** "`backend` covers the video render; the burst merge during download still detects for itself."
- **Reality:** The burst merge passes `config.hardware.backend` when it has a config (`processing/live_photo_merger.py:754-756`). The component that ignores `backend` is clip extraction (`clips.py:47`).
- **Fix:** Name the right stage.
- **Confidence:** LIKELY. It depends on whether callers pass `config`.

### G1-12 [WRONG] config-reference.md:655: `strict_sharing: false` and captions clearing exposure flags
- **Claim:** "Turning it off does not let a caption clear an exposure flag."
- **Reality:** The code says the opposite. The field description reads "False lets a caption that explains the flag clear it for sharing" (`config_models_editorial.py:105-111`). The hold's docstring says it "also holds what only an exposure flag or a flagged clip marked, where a caption that names clothing would otherwise clear it" (`analysis/editorial_shareability.py:464-469`).
- **Fix:** Reconcile the doc and the code, then document whichever is true. This matters to privacy-conscious readers.
- **Confidence:** LIKELY. Two in-code statements contradict the doc; I did not trace every audience rule path.

### G1-13 [GAP] config-reference.md:346 (and troubleshooting.md:156): the bundled track needs the `music` extra
- **Claim:** "Background music uses a bundled track by default." Troubleshooting adds: "falls back to the next one, then to a bundled track."
- **Reality:** The tracks ship in a separate `immich-memories-music` distribution (the `music` extra). `bundled_library()` returns `None` when it is absent. Docker has it. A plain `pip`/`uv` install does not, so that reader gets no music fallback.
- **Evidence:** `audio/bundled_music.py:1-37`.
- **Fix:** Add "(Docker image, or the `music` extra)".
- **Confidence:** VERIFIED for the code. The no-music outcome itself was not executed.

### G1-14 [GAP] config-reference.md:62: `scripts/tier_settings.py` exists only in a source checkout
- **Claim:** "`uv run python scripts/tier_settings.py` prints what each tier runs with."
- **Reality:** `scripts/` is not copied into the image (`docker/Dockerfile` COPY lines 33-99) and is not in the wheel. Docker and pip users cannot run it.
- **Fix:** Say "from a source checkout", or expose the table through a CLI command (`capabilities`?).
- **Confidence:** VERIFIED.

### G1-15 [GAP] config-reference.md:466-472: `reader_concurrency` is ignored for the owned local model
- **Claim:** "`reader_concurrency` limits independent reader jobs in flight (1 to 16)… Left unset, concurrency is read from `base_url`."
- **Reality:** When `base_url` is blank (`runs_locally`), the value is forced to 1 whatever you set (`analysis/llm_providers.py:267-270`).
- **Fix:** Add "The app-owned local model always reads one job at a time."
- **Confidence:** VERIFIED.

### G1-16 [GAP] config-reference.md:177-178: undocumented exclusion rules
- **Claim:** `min_source_short_side` "Drop smaller clips unless they carry camera EXIF". `max_source_video_seconds` "Exclude longer source videos…".
- **Reality:**
  - `min_source_short_side`: a favorite, or media captured before 2008, also overrides. The setting also enables the 2048px UUID-JPEG forwarded-media fingerprint.
  - `max_source_video_seconds`: missing or unreadable duration metadata also excludes the video. A reader whose videos lack duration metadata would see them vanish with no explanation on this page.
- **Evidence:** `config_models_analysis.py:98-121`.
- **Fix:** Add both sentences.
- **Confidence:** VERIFIED against the field descriptions. The selection path was not traced.

### G1-17 [CLARITY] config-reference.md:962-967: `notifications.urls` looks like a default
- **Claim:** The block shows three Apprise URLs under `urls:`, and the default is not stated.
- **Reality:** The default is `[]`. Every other example value on the page is marked "example" (lines 483-484, 527).
- **Fix:** Add `# example; default []`.
- **Confidence:** VERIFIED.

### G1-18 [CLARITY] config-reference.md:563-566: the Laya defaults shown are Apple-only
- **Claim:** The block prints the Apple-silicon Laya defaults (`laya-audience-a79ad9fa.tar`, threshold 0.186), with a comment pointing elsewhere.
- **Reality:** Every Linux, Docker or NAS reader (audiences a and b) gets `laya-audience-onnx-90420ef3.tar.gz` and 0.185 (`laya_checkpoints.py`). The comment is accurate, but it inverts the common case.
- **Fix:** Show the ONNX values, and put the Apple ones in the comment.
- **Confidence:** VERIFIED.

### G1-19 [GAP] config-reference.md, various: allowed ranges missing for some keys
- **Reality:** These validated ranges are missing from the page, so a reader cannot tell what will be refused:
  - `llm.local_context` ≥1024
  - `llm.batch_min_requests` 2-10000
  - `llm.batch_max_wait_minutes` 1-1440
  - `llm.repetition_penalty` >0
  - `inference.timeout_seconds` (0, 300]
  - `editorial.preparation.caption_concurrency` 1-16
  - `editorial.preparation.batch_size` 1-256
  - `editorial.preparation.caption_artifact_id` ≤512 chars
  - `automation.burst_threshold` 1-10
  - `automation.special_days_per_year` 1-100
  - `editorial.people.*` (seat_min_share (0,1], big_story_family_share 0-1, seat_min_pictures ≥1)
  - `editorial.laya_audience_threshold` 0-1
  - `trips.*` ≥1
  - `analysis.min_source_short_side` ≥0
  
  The `trips` section has no comments at all. Nothing says that `0.0/0.0` means "unset" and makes trip memories refuse (`TripsConfig.validate_homebase`), or that the home base also sets the music hemisphere (`TripsConfig.hemisphere`).
- **Fix:** Add the ranges in the existing comment style, plus one line for `trips`.
- **Confidence:** VERIFIED (schema dump).

### G1-20 [POLISH] config-reference.md:842: "Both" names three variables
- "`IMMICH_MEMORIES_DATABASE_URL`, `IMMICH_MEMORIES_DATABASE_SCHEMA` and `IMMICH_MEMORIES_IMPORT_FROM` beat the file. Both are read…" names three variables. Fix: "All three". VERIFIED.

### G1-21 [POLISH] config-reference.md:929 and 51-52: dash substitute and repetition
- Line 929 uses ` -- ` as an em-dash substitute (`https://memories.example.com -- the URL users reach you`), which goes against the voice rule's intent.
- Lines 51-52 say "derived" twice in a row ("…are derived from the product tier. These values are derived rather than separate user controls.").

### G1-22 [WRONG] examples/config.example.yaml (linked from run/config-file.md:107): validates but is stale
`Config.from_yaml` loads it, but:
- Line 47 `network.font_downloads: false` is not a schema key. It is silently ignored (section extras are ignored), and config-reference.md:794 says "Fonts are not a switch".
- Line 20 `quality: high  # high | medium | low` lists retired names. The model maps them (`medium`→balanced, `low`→fast), but the documented values are `high | balanced | fast`.
- Lines 59 and 71 say "six public context heads" and "six-head bundle". The code and docs say eight (config-reference.md:41,549, the `head_bundle` description).
- Line 62 points to `docs-site/docs/being-rewritten/editorial-preparation.md`, which does not exist.
- Line 64 `annotation_database: ""  # blank = annotations.sqlite inside cache.directory`: the field is deprecated, and facts live in the store (field description at `config_models_editorial.py:126-133`).
- Lines 53-57: the `llm` block with `base_url`+`model` and no `enabled` is implicitly enabled (already known, not re-reported). Loading the file logs "The configured LLM can supply titles…".
- **Evidence:** the key-walk script printed `UNKNOWN network.font_downloads`. `ls docs-site/docs/being-rewritten` gives "No such file".
- **Confidence:** VERIFIED.

### G1-23 [CLARITY] faq.md:65: "one a day at most" is the default, not a limit
- **Claim:** "Can it make films on its own? Yes, one a day at most."
- **Reality:** This holds with the defaults (`daily_at` once a day, `cooldown_hours: 24`). But `cooldown_hours` accepts 1-168, and `auto run` via cron or `POST /api/trigger` follows the cooldown, so lowering it allows more than one a day.
- **Fix:** "One a day by default (`automation.cooldown_hours`)."
- **Confidence:** VERIFIED for the schema. The trigger path was not executed.

### G1-24 [CLARITY] faq.md:13-16: upload also creates a tag and an album
- **Claim:** "The one write is the finished film … It writes nothing else."
- **Reality:** Delivery also creates the `immich-memories/generated` tag (`PUT /tags`), creates the album if it is missing (`POST /albums`), adds the asset to the album, and trashes superseded renders. run/privacy.md:48-53 lists all four steps. A privacy-conscious reader (audience c) checking API-key scopes needs those writes.
- **Evidence:** `api/album_service.py:263,267,403,409,449`.
- **Fix:** Add "(plus the tag and album it needs)", or link to privacy.md#what-immich-sees.
- **Confidence:** VERIFIED.

### G1-25 [CLARITY] faq.md:69-73: "one Immich API key" next to multi-account
- **Claim:** "single-user, single-replica: one Immich API key, one library." The next sentence explains adding more accounts, including from the web UI.
- **Reality:** The UI has "Immich accounts to read (primary alone when none are picked)" (`web/src/routes/create/+page.svelte:463`). A reader stumbles on the contradiction.
- **Fix:** "one primary Immich account (the upload target)".
- **Confidence:** VERIFIED.

### G1-26 [CLARITY] troubleshooting.md:109-113: the heading describes a failure the code prevents
- **Claim:** Heading: "A clip fails with 'Could not write header (incorrect codec parameters ?)'".
- **Reality:** `processing/clips.py:504-525` (`_resolve_reencode`) detects VP9/AV1 in `.MOV` before the copy and re-encodes up front, logging "…carries vp9, which QuickTime cannot hold: re-encoding this clip instead of copying it". On a current version the FFmpeg error should not appear. The string is not in `src/`, as expected for an FFmpeg-native message.
- **Fix:** Retitle around the log line users will actually see, or keep the old string as a "versions before X" note.
- **Confidence:** LIKELY. No VP9 MOV was rendered.

### G1-27 [CLARITY] troubleshooting.md:32,102-103: the quoted messages are prefixes
- The table quotes `Waiting for the reader at host:port`, and the text quotes `Gave up on the reader at host:port`.
- The real messages are `Waiting for the reader at {endpoint}: connection dropped, retry N of 3` and `Gave up on the reader at {endpoint} after 3 dropped connections: fix the server and cut again` (`analysis/provider_status.py:36-45`).
- The retry timing "three times, two then four seconds apart" matches `llm_query.py:101-103` (sleep 2.0×drops, `TRANSPORT_RETRIES=3`).
- I found no wording problem. For the owned local model (blank `base_url`), `endpoint_of` returns the raw `base_url`, which would be empty unless it is resolved upstream. I did not verify that.
- **Confidence:** LIKELY.

### G1-28 [CLARITY] troubleshooting.md:30: the env var name differs from the rest of the config pages
- `IMMICH_MEMORIES_DATABASE_URL` (single underscore) is correct: it is read by `db/bootstrap.py:21`. But the mechanical pydantic form `IMMICH_MEMORIES_DATABASE__URL` is also honoured (`config_loader.py:265-267`), and every other config page teaches the `__` form.
- **Fix:** Add one line saying both work, so a Kubernetes operator does not wonder.
- **Confidence:** VERIFIED.

### G1-29 [POLISH] web-ui-details.md:17: copied command and job command differ slightly
- "**Copy as CLI command** copies the command the job runs." The copied command (`web/brief.py:110-112`, `shown_command`) deliberately leaves out the server's `--config` and `--output` arguments, which the job's `argv` includes. That is fine, but "the same cut, minus the server's file paths" would be exact.
- **Confidence:** VERIFIED.

Separate note, not a docs-page finding: several pydantic field descriptions contradict both the docs and the code. `automation.accounts` says "alongside the primary", but the code reads exactly the list (`candidate_discovery.py:353`). `llm.thinking` says "selection review, titles". `editorial.thin_model_layer` says several windows use "the story-first planner", but the code polishes multi-window films too (`editorial_runtime_backend.py:349-360`). These descriptions are not shown in the web UI (no `description` use in SettingsEditor). They would mislead a future docs generator or contributor.

## 3. Mechanical defaults diff (config-reference YAML blocks vs. schema)

Method: I parsed every ```yaml block, unwrapped `advanced:`, flattened the keys, and compared them with field defaults from `Config.model_fields` (aliases honoured, so `database.schema` maps to `schema_name`). I also compared against a resolved `Config.from_yaml(nonexistent, stored={})` with an empty env on this Linux host, which resolves the tier to `nas`.

- **206 of 209 schema keys** appear in a YAML block and were compared. The 3 not shown are `llm.thinking_params` and `llm.no_thinking_params` (shown commented out with the right Qwen default) and `title_llm` (default `None`, shown as an example block).
- **0 genuine default mismatches.** Every comment range and allowed-choice list matches the `Literal`/`ge`/`le` constraints, except the `ultra` prose (G1-1).

Mismatches the diff flagged, all explained:

| Key | Documented | Code default | Match? | Why |
|---|---|---|---|---|
| analysis.max_album_assets | 5000 (tier tip, line 21) | 10000 | n/a | Placement example in the tip; line 181 documents 10000 correctly |
| hardware.encoder_preset | "quality" (tip, line 23) | "balanced" | n/a | Same tip example; line 329 is correct |
| immich.url / api_key | example URL / `${IMMICH_API_KEY}` | "" | n/a | Example values |
| llm.max_tokens_param / drop_params | max_completion_tokens / [temperature] | max_tokens / [] | n/a | Marked "example", default named in the comment |
| triage.encoder_url, free_text.wordnet_url | truncated `https://…/...` | full pinned URL | n/a | Truncated on purpose |
| notifications.urls | 3 sample URLs | [] | **No (unlabelled)** | G1-17 |
| editorial.reader | rules | "auto" field default | yes (resolved) | Tier-derived; resolved NAS value is `rules` |
| editorial.detectors_enabled | false | True field default | yes (resolved) | Tier-derived; NAS resolves `False` |
| editorial.preparation.tier | no_captions | "full" field default | yes (resolved) | Tier-derived; NAS resolves `no_captions` |
| editorial.laya_checkpoint / _url / threshold | Apple MLX values, 0.186 | ONNX values, 0.185 on Linux | platform | Labelled in comment; G1-18 |

## 4. Unverifiable claims (not reported as wrong)

- config-reference:271-275: SSIM, bitrate and MB/min figures per quality preset (measurements).
- config-reference:447-448 (thinking calls 30-134 s vs 4-7 s), 457-460 (reasoning token counts), 713-716 (0.69 s per picture, 42.7 min for 3,709 pictures), 814 (315 KB per preview), 626-627 ("37 of 3,564 photographs").
- config-reference:613: Docling `det-v2` because ONNX layout optimisation mislabels on Celeron J4125.
- config-reference:346-348: ACE-Step generates; MusicGen is the fallback and stem separator; otherwise local Demucs. I did not trace the generator chain.
- config-reference:488-492: Ollama `options` deep-merge and `num_predict` precedence.
- config-reference:516-518: oMLX/Ollama default repetition penalty 1.1.
- config-reference:822: "one `WARNING` per run" for thumbnail overflow; next run reclaims.
- config-reference:884-886: upload filed on the day of the last picture, in the majority timezone.
- config-reference:156-158: speech detection and cut selection run before the worker handoff; music and upload finish on the app.
- faq:39: Samsung and Pixel motion photos untested.
- faq:55: second cut "mostly the render" (performance).
- troubleshooting:85: saved-revision edits bypass sharing and length checks; `--include` still passes the sharing gate.
- troubleshooting:94-95: `runs show` and `report` print the phase-time table.
- troubleshooting:133-134: the audio mixer runs one FFmpeg per clip and names the failing clip.
- troubleshooting:136-138: the owned reader releases its process before local ACE-Step/Demucs.
- web-ui-details:9-14: progress-bar and time-left behaviour (needs a live run).
- web-ui-details:26-28: "past what the titles left, it says the film grows to hold them".
