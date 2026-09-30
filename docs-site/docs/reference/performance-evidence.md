---
title: Measurement methods and results
---

# Measured

What each setup costs in time and calls, measured on a named machine and commit. The quality side
(which pictures each tier keeps) is judged on contact sheets, not in this table. The NAS measurements below cover classifier preparation. Whole-film memory and timing on the
current NAS build are still being validated.

## NAS preparation

The current [NAS preparation table](../better/measured.md#nas-preparation) keeps the comparable measurements and methodology together.

## LLM conformance, 29 September 2026 {#llm-conformance}

The initial four-endpoint run used the complete 34-probe command on
[`b03b6198`](https://github.com/sam-dumont/immich-video-memory-generator/commit/b03b619838074af5c4941190a3bf82baa2afbdcb).
The hosted rows below use that run. The Gemma row uses the complete follow-up with request-specific
JSON modes from [#1662](https://github.com/sam-dumont/immich-video-memory-generator/pull/1662).
The probes cover all 45 model-asking functions found by the source inventory, including shared
adapters. Each probe checks its production result and the call sites it reached. A fallback or
an unreached declared call site fails the probe. A failed probe does not stop the remaining ones.

Inputs were generated text and geometric images. Each banked feature used a fresh temporary
SQLite store. No household library, captions or people file was used. The client ran on the shared
Apple M5 Max described below; the local server was oMLX. Each provider's probes ran sequentially,
and the initial provider runs overlapped. The corrected Gemma follow-up ran on its own.
Server prompt caches could be warm from fixture validation.
These are single runs, with no latency distribution or claim of isolated throughput.

| Endpoint | Passed | Probe time | HTTP attempts | Input / cached input / output tokens | Reported-token cost |
|---|---:|---:|---:|---:|---:|
| OpenAI, gpt-5.6-luna | 32/34 | 124.71s | 87 | 23,521 / 0 / 3,310 | $0.00868, incomplete usage |
| z.ai, glm-5.3-flash, Anthropic-compatible route | 31/34 | 248.31s | 88 | 21,075 / 5,120 / 4,953 | $0.00502 |
| Melious, deepseek-v4.1-flash, `structured_output: false` | 32/34 | 214.88s | 79 | 21,285 / 2,048 / 30,092 | €0.03396 |
| Local oMLX, gemma-4-e4b-it-6bit, request-specific modes | 29/34 | 161.11s | 85 | 20,862 / 6,144 / 7,541 | No API fee |

Probe time sums the per-feature measurements and excludes command startup. HTTP attempts include
retries and rejected requests. Input includes cached input; reasoning tokens are already part of
output and are not added again. Melious reported 26,996 reasoning tokens in its 30,092 output tokens.
OpenAI's title probe made two rejected parameter-negotiation requests without usage reports, so
its price covers reported tokens only. Local hardware and electricity were not priced.

Prices per million tokens, in input / cached-input / output order:
[OpenAI](https://developers.openai.com/api/docs/models/gpt-5.6-luna) $0.20 / $0.02 / $1.20;
[z.ai](https://docs.z.ai/guides/overview/pricing) $0.15 / $0.03 / $0.50;
[Melious](https://melious.ai/pricing) €0.20 / €0.01 / €1.00. These are pay-as-you-go equivalents,
before tax or subscription allowances, not account invoices.

The [initial four-provider CSV](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-29-llm-conformance.csv)
contains all 136 initial rows: calls, token categories, time, validity, quality check, estimated cost and
failure issue numbers. Raw request/reply evidence remains private because provider errors can
contain account details. Reproduce the command from [Add a reader](llm-providers.md#provider-conformance).

### What failed

- OpenAI omitted the recorded trip place under contradictory title instructions
  ([#1651](https://github.com/sam-dumont/immich-video-memory-generator/issues/1651)) and described
  the moving-dot filmstrip as stationary
  ([#1650](https://github.com/sam-dumont/immich-video-memory-generator/issues/1650)).
- z.ai lost the toy-car exclusion when extra prose made the JSON unreadable
  ([#1646](https://github.com/sam-dumont/immich-video-memory-generator/issues/1646)). Its request
  reader returned strings where arrays were expected, which also broke the requested pool
  ([#1645](https://github.com/sam-dumont/immich-video-memory-generator/issues/1645)).
- Melious failed the request-reading and pool checks for the same array-contract problem
  ([#1645](https://github.com/sam-dumont/immich-video-memory-generator/issues/1645)). Its other
  32 checks passed in this run.
- Gemma's corrected run failed two free-text meaning checks: a young form and a restrictive
  qualifier were lost ([#1660](https://github.com/sam-dumont/immich-video-memory-generator/issues/1660)).
  It also failed the caption/motion contracts
  ([#1649](https://github.com/sam-dumont/immich-video-memory-generator/issues/1649)) and gave the
  routine sofa scene the same central status as the race
  ([#1653](https://github.com/sam-dumont/immich-video-memory-generator/issues/1653)).

### Gemma: JSON enforcement changes the result

The initial 17/34 score measured the former local defaults, including an integration regression.
The local-endpoint workaround for an episode-schema decoder stall also disabled free-text schemas
([#1659](https://github.com/sam-dumont/immich-video-memory-generator/issues/1659)). Captured requests
confirm that no `response_format` reached the server in the initial run.

A follow-up changed only `structured_output` to `true` and replayed the same 14 free-text probes.
They improved from **1/14 to 12/14**, with 53 HTTP calls in 94.29 seconds, 5,616 input tokens and
5,771 output tokens. All requests carried `response_format.type=json_schema`. The two remaining
failures lost young forms and a restrictive subject qualifier
([#1660](https://github.com/sam-dumont/immich-video-memory-generator/issues/1660)). Six replies still
hit their token limits, so enabling strict schemas everywhere would need separate verification
of the episode-reading path.

The [forced-JSON subset CSV](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-29-gemma-forced-json.csv)
keeps these measurements separate. That subset check did not rerun the other 20 features and was
not used to calculate an overall score.

A subsequent **complete 34-probe rerun passed 29/34** with the request-specific default. It
combined mode fix [`79062dd9`](https://github.com/sam-dumont/immich-video-memory-generator/commit/79062dd9)
with conformance suite [`924dec19`](https://github.com/sam-dumont/immich-video-memory-generator/commit/924dec19).
The [corrected full-run CSV](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-29-gemma-request-modes.csv)
records every feature, its actual response schema and remaining issue. Both full and lean episode
readings passed without a response schema; free-text and trip titles received their schemas.
The [trip-classification reproduction](https://github.com/sam-dumont/immich-video-memory-generator/issues/1652)
passed too. Six free-text replies still truncated,
including retries within a pool probe whose final selected pool passed.

A preceding Melious attempt lost DNS resolution after eleven probes and was repeated in full
once resolution recovered ([#1657](https://github.com/sam-dumont/immich-video-memory-generator/issues/1657)).
That interrupted attempt is outside the completed-run table: its reported-token cost was at least
€0.01057, with 23 rows lacking complete usage. Earlier fixture-development runs are also outside
the table. The measurements describe the finalized fixtures, not the total development bill.

A pass checks a small production feature, not the quality of a finished film. These failures
remain visible in the support table; a working API connection is not evidence that every feature
works. The suite also does not test asynchronous batch delivery.

## Selection comparison, 27 September 2026

The comparison covered **28 cases across NAS, GPU and Full: 84 attempts**. The cases included
four years, seven months, four trips, three seasons, six people selections and four special days.
All used commit [`9eb16812`](https://github.com/sam-dumont/immich-video-memory-generator/commit/9eb168126c0f24f6cced39a0316f0045132e56c8)
with matched inputs and non-tier settings. Later performance and replacement fixes are not
included in these timings.

The host was an **Apple M5 Max with 128 GB unified memory**, shared with other work. NAS here
means the CPU selection tier running on that Mac, not a measurement of a small NAS appliance.
Full used local Gemma 4 E4B 6-bit; the caption provider was SmolVLM2 500M. Sharing used rules,
picture classifiers and, on GPU and Full, Laya. No sharing request went to the prose model.

### Cache state matters

These were fresh selections using retained media, classifier facts and caption banks. Missing
or changed-version facts were computed where needed. Only **26 new picture captions** were
produced across the batch, so this does not measure cold caption throughput.

The first 26 attempts each started from the same seed. That repeated some preparation between
tiers. From the next attempt, GPU inherited its paired NAS preparation, and Full inherited GPU.
The tables keep those two methods separate.

**The cold-year target of under one hour on 8–16 GB remains unverified.** A quick Full refinement
does not include the work already done by NAS and GPU. One `nas`-tier year alone took 72 minutes on the M5 Max.

### The `nas` tier, on the M5 Max's CPU

These are ranges across the cases in each group, rounded to the nearest second. CLI time
includes acquisition, selection and any post-selection metadata work. Video rendering, music,
cache-copy staging and waiting for another job are outside it.

| Cases | `nas` tier CLI time (M5 Max) |
|---|---:|
| Years (4 runs) | 4m14s–72m37s |
| Months (7 runs) | 49s–10m45s |
| Trips (4 runs) | 2m56s–12m02s |
| Seasons (3 runs) | 2m39s–20m54s |
| People (6 runs) | 4m13s–21m04s |
| Special days (4 runs) | 39s–1m42s |

### Additional work after the previous tier

Each entry is the extra CLI time after the preceding layer, not total time from an empty cache.
The GPU and Full year samples differ: only one GPU year and two Full years used this method.

| Layer and cases | Additional CLI time |
|---|---:|
| GPU, years (1 run) | 2m56s |
| Full, years (2 runs) | 30m36s–41m02s |
| GPU, months (1 run) | 27s |
| Full, months (1 run) | 2m12s |
| GPU, trips (4 runs) | 18s–1m26s |
| Full, trips (4 runs) | 4m41s–7m01s |
| GPU, seasons (3 runs) | 28s–1m27s |
| Full, seasons (3 runs) | 4m25s–9m41s |
| GPU, people (6 runs) | 46s–2m20s |
| Full, people (6 runs) | 9m20s–15m44s |
| GPU, special days (4 runs) | 15s–21s |
| Full, special days (4 runs) | 34s–2m23s |

The ranges include unsuccessful attempts: one degraded Full year, one failed Full season check,
one failed GPU people check and one Full people execution failure. Their cost is retained.

### Earlier independent runs

These 17 GPU/Full attempts repeated preparation from the seed. Treat them as standalone
measurements with existing banks, not the extra cost of enabling the next layer.

| Layer and cases | CLI time |
|---|---:|
| GPU, years (3 runs) | 2m20s–61m04s |
| Full, years (2 runs) | 16m10s–16m18s |
| GPU, months (6 runs) | 48s–10m02s |
| Full, months (6 runs) | 1m40s–6m42s |

In the slowest GPU year, CPU classification alone took about 36 minutes. It produced no new
picture captions. That repeated baseline work belongs to this measurement method; it is not
Gemma's refinement cost.

### Results, calls and memory

- **83 selections finished; one execution failed.** Of all 84 attempts, 80 passed the recorded
  selection and reader checks, two failed a selection check, and one had incomplete episode
  reading. Passing these checks is separate from judging the pictures or watching a rendered film.
- **All 28 cases received a private picture-and-reason review.** The owner has not made a final
  preference decision. Ten finished selections carried the existing duration-shortfall label;
  estimated playback is not a measurement of rendered duration.
- **1,627 Gemma and 137 SmolVLM calls were metered**, including failed work. Existing captions
  were reused. No external LLM or retired 30B calls were observed. There was no hosted-request
  charge; hardware and electricity costs were not measured.
- **Memory is not a sizing result.** Process RSS was sampled on a shared host; service activity
  could belong to other jobs, and RSS is not GPU memory. This batch does not prove an 8–16 GB fit.

The [aggregate CSV](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-27-selection-matrix-aggregates.csv)
keeps the counts, exact timing ranges, medians and failure categories behind these tables.
Household pictures, prompts, identities and individual case records remain private.

For a setup decision, compare your own NAS draft with the refined result. Keep the captions and
facts already computed, measure the added work, and decide whether the changes earn their cost.
Discovery and free-text memories were not tested by this comparison.

## Earlier runs

The dated reports stay in the repository, with every cell and its caveats, for anyone who wants the
history:

- [Setup matrix, 17 September 2026](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-17-setup-matrix.md):
  a Mac, a Synology NAS and a Kubernetes cluster over one fixture month and one real month, on
  `0.102.0`.
- [Capability matrix, 12 September 2026](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-12-capability-matrix.md):
  every memory type on a workstation, and `metadata_only` on the NAS.
- [Deployment costs, 12 September 2026](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/docs/research/2026-09-12-deployment-costs.md):
  what each layout needed to stand up.

How to run the matrix yourself: [Setup matrix](../contribute/setup-matrix.md).
