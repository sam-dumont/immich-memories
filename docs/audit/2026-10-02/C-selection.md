# Audit C: how-it-chooses + reference/selection-internals

Paths are relative to the repo root. `docs/` means `docs-site/docs/`, and `src/` means `src/immich_memories/`.

## 1. Coverage

| Page | Claims checked (approx) | Findings | Verdict |
|---|---|---|---|
| how-it-chooses/overview.md | 14 | 1 (C-3) | Accurate. It does not link three of its sibling pages |
| how-it-chooses/moments-and-stories.md | 8 | 1 (C-3) | Accurate, but no sidebar entry or inbound link points to it (orphan) |
| how-it-chooses/picking-shots.md | 10 | 2 (C-3, C-12) | Numbers are right (6 s / 12 s / 2 s). Not in the sidebar |
| how-it-chooses/length-and-filler.md | 9 | 1 (C-8) | Accurate. The "Default lengths" link goes to a page that does not list them |
| how-it-chooses/family-audience-duplicates.md | 14 | 2 (C-9, C-14) | Accurate. The default is shown in the UI as "As configured". Undefined jargon |
| how-it-chooses/overrule-it.md | 25 | 2 (C-1, C-9) | The Never use / tick claim is wrong. Every UI label checked is correct |
| how-it-chooses/what-a-model-adds.md | 7 | 2 (C-3, C-14) | Accurate. Not in the sidebar. "Laya" and "reader" are undefined |
| how-it-chooses/glossary.md | 8 | 1 (C-15) | Accurate |
| selection-internals/overview.md | 30 | 2 (C-6, C-16) | Accurate. Link text uses the old page name |
| selection-internals/moments-and-stories.md | 45 | 5 (C-2, C-5, C-10, C-11, C-17) | Mostly exact. The every-year rule is wrong for two film kinds. Slot math is simplified |
| selection-internals/picking-shots.md | 45 | 3 (C-6, C-12, C-18) | The ranking keys and the standing table match the code to the half point |
| selection-internals/length-and-filler.md | 30 | 3 (C-6, C-8, C-19) | The constants match `editorial_structure_budget.py` |
| selection-internals/family-audience-duplicates.md | 55 | 4 (C-4, C-7, C-13, C-6) | The thresholds match the code. "On the storyboard" is wrong. A measured number disagrees with the code |
| selection-internals/what-a-model-adds.md | 35 | 1 (C-15) | Budgets, block size, 2*ceil(S/3.5) and the 150-word thesis all match |
| selection-internals/pixel-evidence.md | 12 | 1 (C-16) | A verbatim copy of part of overview.md, with no intro |
| selection-internals/glossary.md | 45 | 2 (C-15, C-17) | Every file and symbol named in the Where column exists. A few labels are loose |

## 2. Findings

### C-1 [WRONG] how-it-chooses/overrule-it.md:25 "A persistent Never use decision must be undone first"
- Claim: before ticking a picture into a cut in the pool, you must undo its Never use decision.
- Reality: nothing enforces this. In the pool page the checkbox is always enabled (`web/src/routes/runs/[run_id]/pool/+page.svelte:125-126`). `preview()` posts `added` without filtering out never-use pictures (lines 75-84). The server's `save_revision` / `_checked` / `_checked_additions` (`src/operations/cut_revisions.py:159-216`) refuse only pictures that are outside the pool, already in the cut, or added twice. The module docstring (lines 3-6) says a revision plays "what they decided ... with no detector or hold standing in the way". `operations/revision_render.py` also has no never-use check.
- Fix: delete the sentence, or say that ticking overrides Never use for this cut only. Alternatively, file a code bug if the doc states the intent.
- Confidence: LIKELY (code read; the UI was not run).

### C-2 [WRONG] selection-internals/moments-and-stories.md:152-158 "Every year gets a shot": person film over several ranges, and custom film
- Claim: "a person film over several date ranges [is split] into those ranges, and a custom film over several ranges likewise. Before any story takes a second shot, each year (or range) ... gets one."
- Reality:
  - In `src/analysis/editorial_intent.py:268-300` (`_person`), the partitions are per window, but `voice_per_partition=eras`. That is True only for a single span longer than 548 days. A multi-window person film therefore gets no per-range shot: `allocate_slots` only runs `take_one_per_era` when `era_of` is set, and `voiced_era_of` returns None when `voice_per_partition` is False (lines 140-150).
  - A multi-range custom film is split per calendar year (`_custom`, lines 365-379: `partitions = _per_year(whole)`), not per range.
  - A curated album with `--subject` also gets one per year (`yearly = len(spans) > 1 or pool`), and this paragraph does not list it.
- Fix: "A person film of one window longer than 18 months, a custom film over several ranges, and an album with a written subject are split into calendar years." Drop "person film over several ranges".
- Confidence: VERIFIED by reading the code.

### C-3 [GAP] how-it-chooses: three pages are missing from the sidebar, and one is orphaned
- Reality: `docs-site/sidebars.ts:7-27,93` lists only overview, overrule-it, length-and-filler, family-audience-duplicates and glossary from `how-it-chooses/`. `moments-and-stories`, `picking-shots` and `what-a-model-adds` are absent.
  - Nothing in the docs links to `how-it-chooses/moments-and-stories.md` (`grep -rn moments-and-stories docs` finds only internals links and the page's own outbound link).
  - `how-it-chooses/overview.md` links to none of the three.
  - `picking-shots` is reached only from `reference/caption-service.md:350`.
- Fix: add the three pages to the "Make and improve films" category or under the overview, and link them from overview.md.
- Confidence: VERIFIED.

### C-4 [WRONG] selection-internals/family-audience-duplicates.md:188 "in the media pool, on the storyboard or with `pictures` in the CLI"
- Reality: the hold actions (Never use / Clear hold / Undo, POST `/pictures/{id}/decision`) appear only in `web/src/routes/runs/[run_id]/pool/+page.svelte:137-142`. `lib/ShotInspector.svelte` (the contact sheet / storyboard inspector) has no decision controls. It only has a "Browse the whole pool" link at line 128. `grep -rn "decision\|Clear hold" web/src` finds no other component.
- Fix: "in the pool or with `pictures` in the CLI".
- Confidence: VERIFIED (source grep).

### C-5 [WRONG] selection-internals/moments-and-stories.md:117-118 how the slot count is computed
- Claim: "The film's slot count is its target length divided by the average hold of its material (about 4 s a shot)".
- Reality: `slots_total = int(content_budget // SECONDS_PER_SLOT)` with `SECONDS_PER_SLOT = NOMINAL_STILL_SECONDS = 4.0` (`src/analysis/editorial_structure_planner.py:107,224-226`). The dividend is the render timing's content budget, which is the target minus the title and ending reserve (`processing/editorial_timing.py:79-90`). It is not the target length. The divisor is a fixed 4.0 s, not the material's average hold.
- Fix: "its content seconds (the target minus title and ending cards) divided by a fixed 4 s".
- Confidence: VERIFIED.

### C-6 [CLARITY] internals pages use "ticked" for `--include`, while UI pool ticks never reach these rules
- Pages and lines: picking-shots.md:86 ("a picture you ticked, scores 2"), length-and-filler.md:43-44 ("A picture you ticked is never dropped ... not ticked"), family-audience-duplicates.md:242 ("one you ticked"), what-a-model-adds.md:70-71 ("Your ticks are added back after the polish").
- Reality: these rules read `owner_required_asset_ids`, which comes only from `generate --include` (`cli/generate.py:516,723`; `RuleStructureReader.standing` at `editorial_rule_reader.py:459`; `trim_to_timing(..., protected=required)` at `editorial_structure_planner.py:501`). A pool tick saves a revision and nothing is chosen again (`pool/+page.svelte:74,107`; `cut_revisions.py:3`). The web job never passes `--include` (`web/job_routes.py` has no include/exclude).
- Why readers stumble: an operator who ticks in the pool will expect standing 2, trim protection and so on. Those never apply, because the pool tick bypasses selection entirely.
- Fix: say "a picture you passed with `--include`" in these four places.
- Confidence: VERIFIED.

### C-7 [WRONG / inconsistent] selection-internals/family-audience-duplicates.md:220-221 "On one real month that was 415 of 2,028 files"
- Reality: the code that implements this rule says "Measured on one February: 352 of 2,028 files were such copies" (`src/analysis/picture_copies.py:6`). No source has 415.
- Fix: reconcile with the measurement. If dated, move it to `better/measured.md`, which is the only page with dates.
- Confidence: LIKELY. I cannot tell which number is current, but the doc and the code disagree.

### C-8 [GAP] how-it-chooses/length-and-filler.md:21 and selection-internals/length-and-filler.md:19-20 link to the wrong page for lengths
- Claim: "Default lengths are on Memory types". Internals: "How the target itself is set (per memory type, per active day, `--duration`) is on Memory types#how-long-a-film-runs".
- Reality: `docs/make/memory-types.mdx:24-28` gives no default lengths and no per-active-day rule. It links on to `reference/film-types.mdx#how-long-a-film-runs`. That section (lines 29-50) holds the 30 s/day cap, 30 s + 10 s/day, the 60 s to 5 min range, and so on.
- Fix: link straight to `reference/film-types.mdx#how-long-a-film-runs`.
- Confidence: VERIFIED.

### C-9 [CLARITY] how-it-chooses/family-audience-duplicates.md:7 and overrule-it.md:40 "The default is Family"
- Reality: the brief's **Who may see it** select defaults to **As configured** (`web/src/routes/create/+page.svelte:480-483`, `<option value="">As configured</option>`). That resolves to `defaults.sharing`, which defaults to `family` (`src/config_models_render.py:65-71`).
- Why readers stumble: a newcomer opens the brief, sees "As configured" rather than "Family", and is not told what it means.
- Fix: "The default, shown as **As configured**, is Family unless `defaults.sharing` says otherwise."
- Confidence: VERIFIED.

### C-10 [CLARITY] selection-internals/moments-and-stories.md:36 day-chunk rule is described slightly off
- Claim: "starting within 6 hours of the last picture ... split only when more than 90 minutes pass and the city changes".
- Reality: `_day_chunks` (`editorial_rule_reader.py:174-197`) compares moment start times: the chunk's last moment start (`last[0]`), not its last picture. It joins when the moment is on the same calendar day as the chunk's first moment, or starts within 6 h of the last moment's start (`_same_episode_day`, `editorial_story_reading.py:356-366`). The 90-minute gap (`gap > 5400`) is also measured between moment starts, and the city is compared on each moment's first picture.
- Fix: replace "last picture" with "last moment's start".
- Confidence: VERIFIED.

### C-11 [GAP] selection-internals/moments-and-stories.md:83-113 the worthiness reading is never defined on the page that names it
- Reality: the page says "Each happening is first read for whether it is worth remembering, from facts alone" and maps remarkable / maybe / background to weights. It never says what produces each reading. In `RuleStructureReader._vote` / `_indicator` (`editorial_rule_reader.py:120-143`):
  - remarkable: a day at or above the day threshold, away from home, or outside the 12 usual cities. Every happening of an album film also reads remarkable.
  - maybe: a favourite, close family, a video, or the only happening of a required part.
  - background: everything else.
- Line 112 then quotes "The 12 usual cities" as if the term had been introduced, but it appears only on length-and-filler.md:58.
- Also: length-and-filler.md:57-59 lists "indicators" without saying that a favourite or a video gives only `maybe` (glimpse, 1 shot), while a busy day or being away gives `remarkable` (minor).
- Also missing: the strangers cap (line 108) does not apply to a trip or a journey film (`editorial_story_weighing.py:513-519`).
- Fix: add the three-way rule table.
- Confidence: VERIFIED.

### C-12 [CLARITY] album standing and `--subject` "needs a model": docs and CLI help disagree
- Reality:
  - picking-shots.md:129-137 and how-it-chooses/picking-shots.md:13 present an album with a written subject as part of the no-model rules ("Every rule here runs on a plain NAS", internals line 14).
  - `generate --help` says `--subject` "Needs a model reader". Command: `uv run --no-sync immich-memories generate --help | grep -A8 -- "--subject TEXT"`.
  - I found no enforcement in `cli/`. The only check is `generate_resolution.py:302`, which requires `--from-album`.
  - Separately, `RuleStructureReader.standing` returns 2 for every album film, with or without a subject, once the zero rules pass (`editorial_rule_reader.py:462-463`). The standing section ("Otherwise the heads decide") does not mention this.
- Fix: reconcile the CLI help and the docs. Add the album-film standing default.
- Confidence: LIKELY. I did not run the rules tier against an album.

### C-13 [CLARITY] selection-internals/family-audience-duplicates.md:205-206 "the web page and the CLI can't overwrite each other's"
- Reality: `owner_decisions.decide` "Record[s] the owner's decision on one picture, replacing any earlier one" (`src/store/owner_decisions.py:73-102`, via `_drop_owner_rows`). A later CLI decision replaces an earlier web decision on the same picture.
- Fix: "one decision per picture, whichever surface set it last".
- Confidence: VERIFIED.

### C-14 [CLARITY] how-it-chooses pages: jargon a newcomer cannot decode
- family-audience-duplicates.md:19 uses "GPU and Full add descriptions and Laya's activity check". "Full" and "Laya" are not explained, and the how-it-chooses glossary has no "Laya" entry.
- what-a-model-adds.md:7-9 uses "rules editor", "selection reader", "hosted reader" and "the local Laya classifier".
- glossary.md has "Tier" but not "reader" or "Laya".
- Fix: add glossary rows for Reader, Laya and Rules draft, or reword the sentences.
- Confidence: VERIFIED (text read).

### C-15 [CLARITY] selection-internals glossary / what-a-model-adds: smaller inconsistencies
- glossary.md:89 says "Block vote ... asked in two orders". what-a-model-adds.md:58-59 says the second, hashed order is asked "only when the first named a shot it may move". The code has a `Settled` callable that lets one order settle a row (`editorial_block_votes.py:32-36`). The glossary should say "up to two orders".
- glossary.md:44: `RESIDUAL_MIN` lives in `editorial_structure_budget.py:15`, not `editorial_motion_facts.py`. That file hard-codes `threshold=1.5`.
- glossary.md:56 and moments-and-stories.md:104: "mostly close family" for a 30 % share is misleading. 0.3 is not "mostly".
- Confidence: VERIFIED.

### C-16 [CLARITY] selection-internals/pixel-evidence.md duplicates overview.md:83-131 word for word
- Reality: pixel-evidence lines 9-55 are identical to overview lines 85-131, including the table and the diagram. pixel-evidence has no H1 intro, only "## Scope and timing". The sidebar is autogenerated with no `sidebar_position` in any front matter (every page has only `title:`). Docusaurus therefore orders it by file name: family-audience-duplicates, glossary, length-and-filler, moments-and-stories, overview ("From library to film"), picking-shots, pixel-evidence, what-a-model-adds. The overview comes fifth and the glossary second.
- Related POLISH: selection-internals/overview.md:58 and family-audience-duplicates.md:189 use the link text "Overrule it", but the target is titled "Edit the cut" (sidebar label `sidebars.ts:20`). troubleshooting.md:87 and faq.md:51 do the same.
- Fix: remove one copy (keep pixel-evidence and link to it from the overview), and add `sidebar_position`.
- Confidence: VERIFIED for the duplication and the front matter. The ordering is LIKELY: it is Docusaurus default behaviour, and I did not build the site.

### C-17 [CLARITY] selection-internals/moments-and-stories.md:38,137-144,171 smaller rule gaps
- Trip legs: the doc says "a trip splits only when two legs are more than 50 km apart". The code splits not at all if any adjacent pair is within 50 km (`trip_legs.py:43-48`).
- Same kind: only `minor`/`major` stories qualify, not `glimpse` or `none` (`editorial_same_kind.py:59`). "the whole film otherwise" ignores that long person films are partitioned by year.
- Route C: "Trips fold into one story per leg" reads as Route C only, but the no-model path already splits trips into legs (line 38). What is Route C only is the reserve.
- Line 121 (minor "2, or 1 in a film under 8 slots") and the handout order match `weight_caps` / `allocate_slots` (`editorial_story_slots.py:20-28,222-236`). Lines 107-110: the "major" ordered-only rule also applies to `dominant`, and needs more than 2 pictures (`editorial_story_standing.py:154-157`). picking-shots.md:121 says only "major".
- Confidence: VERIFIED.

### C-18 [GAP] selection-internals/picking-shots.md:82-95 standing omits two rules
- In a shareable film, an exposure-flagged picture scores 0 unless the owner cleared it (`editorial_rule_reader.py:451-461`).
- With heads only, `activity == "animal-nature"` is never refused (`editorial_standing_facts.py:268`). The doc gives the animal exception only for captions.
- Confidence: VERIFIED.

### C-19 [CLARITY] selection-internals/length-and-filler.md:33 "A Live Photo playing as its still | 4.0 s"
- Reality: in a no-model draft, a live-still takes `_still_hold`, which is 3.5 s without a star or a known person (`editorial_structure_material.py:216-224,262`). Only after motion measurement is it set to 4.0 s (`editorial_motion_facts.py:213-214`).
- Confidence: VERIFIED.

### C-20 [POLISH]
- length-and-filler.md:86 "What left is listed": a grammar slip.
- picking-shots.md:189-190: a double blank line under the heading.
- Curly apostrophes are mixed with straight ones: how-it-chooses/family-audience-duplicates.md:19,21,27,29; what-a-model-adds.md:7; internals picking-shots.md:91.
- 15 internals mermaid diagrams have no `accTitle`/`accDescr`. Only how-it-chooses/overview.md has them.
- No em dashes or chatbot words were found in the 16 pages (grep).

### Cross-page notes (outside my pages, found while checking)
- The `thin_model_layer` pydantic description (`src/config_models_editorial.py:94-101`) says it "Needs one window of dates; a film over several windows is planned with the story-first planner". The code (`editorial_runtime_backend.py:349-360`) and config-reference.md:646 say multi-window films use the polish. The description is stale, and the docs are right.
- `reference/film-types.mdx:44` links "Length, quiet weeks and filler" to `how-it-chooses/length-and-filler.md`. That page is titled "Why a film is shorter". The internals page carries the linked title.

## 3. Verified correct (spot list)
- Moment 10 min / 2 km and episode 90 min (`moment_grouping.py:32-43`).
- Capture run 300 s (`editorial_story_shortlist.py:25`).
- Home radius 10 km (`editorial_home_radius.py:8`).
- Legs: 25 km, 3 days, 50 km.
- Day threshold max(4×median, p75).
- Event rule: ≥2 moments, 1 km, 18 h, reserve 2/3, result words.
- `GATE_WEIGHT`.
- `weight_caps`.
- Big story 2.0 / 0.3.
- Seat 20 / 5 %.
- Trip allowance formula.
- Same-kind 10 km.
- 548 days.
- `max(6, 3×shots)`.
- `rule_representative_rank` key order (all 10 keys).
- Subject rung 1-3.
- All three standing tables, entry by entry.
- 6/8 frames (0.75).
- Look-alike 10 bits.
- Final review 6 bits, cosine 0.65, 14 days, favourite twins 2 days, one moment on the same day.
- Keep order in duplicate review.
- Burst 300 s / 8 bits.
- Forwarded copies 2 bits.
- Holds 4.0/3.5, 6.0 cap, 2.0 minimum, 12 s speech cap, +0.5 ends to 5.0.
- Shave 0.5 s down to 3.5 s.
- 15 % tolerance and status names.
- Filler kinds and indicators.
- Chain 50 % / 3.
- Review list 0.2-0.5.
- Laya's 4 just_us findings and 4 do_not_show findings.
- Clean-evidence conditions.
- `strict_sharing` and `thin_model_layer` defaults.
- `reader_concurrency` 1/4.
- `max_source_video_seconds` 300.
- Tier table and the reader override warning (`config_tiers.py`).
- Polish: block 12, budget 4/12 shots + 4/seat + 1/3 episodes, 2×ceil(S/3.5), 12-row pages, 8 accounts per page, 150-word thesis, failure log string.
- Title memory types.
- Mood fallback "calm".
- Laya 0.4B and `models fetch --laya`.
- CLI flags exist: `--include`, `--exclude`, `--sharing`, `--duration`, `--from-album`, `--subject`, `--llm-title`, `--accounts`, `--no-render`, `runs why|story|show`, `prepare --overviews`, `pictures`.
- UI labels exist verbatim: Remove from this cut, Start here, End here, Other pictures of this moment, Use this picture instead, Keep the original, Save revision, What to render, Undo, Discard changes, Pool, Preview with these choices, Never use, Clear hold, Who may see it, Just us/Family/Shareable/Anyone, Settings People.
- All internal links and anchors resolve.

## 4. Unverifiable
- "a special day that keeps two good clips gets a 13-second film" and "three photographed days ≈ 20 s": these depend on title timing, and I did not render.
- "A period with no pictures ... exit 1": I did not run generate.
- "`runs why` prints yours last": I did not trace the output order.
- The audience bank lifetime ("a text reading's lasts as long as the audience prompt").
- The detailed seat mechanics (R/T/D page ordering, revocation, "one more try") were only partly traced in `editorial_thin_refill.py`.
- "only confirmed roles count" (overrule-it:57): I did not trace the registry confirmation filter.
- "one Immich search per word" for OCR corroboration: I did not trace `printed_near`.
- NAS LLM-caption opt-in actually captioning, given that `nas` sets `preparation.tier=no_captions` while `demands_captions` is true for `caption_provider: llm`. Not executed.
