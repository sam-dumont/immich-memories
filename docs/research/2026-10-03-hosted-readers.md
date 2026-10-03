# Hosted reader rerun, 3 October 2026

Evidence for [#1718](https://github.com/sam-dumont/immich-memories/issues/1718), with the baseline on remote `main` commit `870b71cab23c1f8f1e7b0839e77662a757b963c6`. The corrected synthetic suites and annual discovery use JSON contract fix `8961ccef76da8942ce83252832df1546b82f7fe2`. Every exported row names its source commit. Historical results from #1513 and the October 1 contract checks are separate measurements.

## What a hosted reader costs

The same monthly request produced a roughly one-minute, 15-picture film with every provider:

| Provider | App end-to-end | Film duration | Estimated API cost | Same tokens without provider cache discount |
|---|---:|---:|---:|---:|
| OpenAI | 77.516 s | 60.817 s | $0.00963612 | $0.01693980 |
| z.ai | 120.057 s | 60.917 s | $0.01256200 | $0.01256200 |
| Melious | 180.353 s | 60.917 s | €0.06631056 | €0.06708880 |

All three passed full audio/video decoding. These are observed single-run waits, not quality endorsements or an isolated throughput ranking. OpenAI's run used warm provider cache reads. Melious reported 49,993 reasoning tokens out of 51,541 output tokens, including recovery from two truncated answers, one of them empty. Reported recovery usage is included.

Costs below are estimates from the tokens each provider reported and its published pay-as-you-go rates checked on October 3. They are not account receipts. The account's subscription allocation and marginal charge are unknown. A fixed subscription payment is separate from the estimated per-task list price.

| Provider and exact model | Input / million | Cached input / million | Output / million |
|---|---:|---:|---:|
| [OpenAI, gpt-5.6-luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) | $0.20 | $0.02 | $1.20 |
| [z.ai, glm-5.3-flash](https://docs.z.ai/guides/overview/pricing) | $0.15 | $0.03 | $0.50 |
| [Melious, deepseek-v4.1-flash](https://melious.ai/pricing) | €0.20 | €0.01 | €1.00 |

Calculation: `(input - cached input) × input rate + cached input × cache rate + output × output rate`, divided by one million, before any applicable taxes. Reasoning tokens are already included in output tokens and are not charged twice. Currencies stay separate. Missing usage or rates stay unknown. Error responses without usage are unpriced; estimates cover the reported tokens, not a guaranteed final bill.

## Complete synthetic suite

All 34 cases used the production client, its normal recovery and feature-specific meaning checks. Fresh temporary stores isolated every banked case. Images were generated geometric fixtures. The suite's call-site inventory guard reported no uncovered entry points.

| Revision / provider | Passed | Suite elapsed | Sum of feature times | HTTP attempts | Input / cached / output tokens | Estimated reader cost |
|---|---:|---:|---:|---:|---:|---:|
| Baseline, OpenAI | 33/34 | 123.84 s | 122.97 s | 87 | 28,954 / 0 / 3,177 | $0.00960320 |
| Baseline, z.ai | 34/34 | 200.18 s | 199.27 s | 85 | 25,971 / 0 / 3,932 | $0.00586165 |
| Baseline, Melious | 34/34 | 139.88 s | 138.97 s | 86 | 33,719 / 2,816 / 48,917 | €0.05512576 |
| Corrected, OpenAI | 33/34 | 114.69 s | 113.78 s | 87 | 28,949 / 0 / 3,228 | $0.00966340 |
| Corrected, z.ai | 33/34 | 192.26 s | 191.36 s | 86 | 27,022 / 0 / 4,215 | $0.00616080 |
| Corrected, Melious | 34/34 | 543.41 s | 542.45 s | 86 | 33,673 / 1,536 / 25,283 | €0.03172576 |

Each row is one run per endpoint on a shared Apple M5 Max host; provider runs partly overlapped. They establish observed waiting time, not an isolated throughput ranking. Server caches may already have been warm. Preparation of a personal library and film rendering are excluded.

In the baseline, OpenAI missed the right-moving dot. All three endpoints returned 85 HTTP 200 responses; OpenAI also made two HTTP 400 negotiation attempts and Melious made one. Melious recovered from one empty, truncated answer. Its 45,651 reasoning tokens account for most output usage; OpenAI reported 138 and z.ai did not report that counter.

The corrected suites returned no empty or truncated answers. OpenAI still failed video motion; z.ai failed free-text request reading; Melious passed all 34 checks. Reported recovery usage is included.

z.ai's repeated free-text request-reading check dropped the synthetic subject ‘cats’. That path was unchanged by the JSON fix. This is a repeatability failure, not evidence that the format fix caused it. HTTP success and feature correctness remain separate.

To repeat the synthetic checks from a recorded source revision, use the existing target with a provider config naming the exact route and model above:

```bash
make dev
make llm-conformance CONFIG=provider.yaml OUTPUT=output/hosted-reader-check
```

Keep `enabled: true`, `thinking: low` and `structured_output: null`. The target makes real provider calls, records private request/reply evidence, and returns nonzero when a feature fails. It does not render a film or prepare a personal library.

## Merged Ollama comparison

The Ollama results were checked against all 142 rows merged in [PR #1919](https://github.com/sam-dumont/immich-memories/pull/1919): 136 feature-suite rows and six larger-prompt probes. They use product revision `a3bfc5dbe66efceaf6985abed72c78600a0fbb37`, Ollama 0.35.1, `gemma4:e4b-it-q4_K_M`, an M5 Max with 128 GiB RAM and a 32,768-token context. These are the merged observations, not new runs of the JSON fix below.

| Ollama route and setting | Passed | Sum of feature times | HTTP attempts | Hosted API fee |
|---|---:|---:|---:|---:|
| Native, server-default thinking | 34/34 | 318.77 s | 85 | None |
| Native, `think: false` | 33/34 | 53.01 s | 85 | None |
| Compatible, default app settings | 25/34 | 345.19 s | 97 | None |
| Compatible, `reasoning_effort: none` | 32/34 | 45.04 s | 85 | None |

The thinking-off native route missed motion; the compatible route also lost a fact from the period summary. Both read all 22 episodes and selected eight story moments in separate larger-prompt probes. Native server-default thinking truncated the first large episode response despite passing all 34 smaller feature checks.

The times sum individual feature probes; the hosted table includes that sum and complete-suite elapsed time. Neither includes film rendering. These were separate runs with potentially warm caches, different model weights and source revisions, not a controlled speed ranking. Local Ollama has no hosted token charge; electricity and hardware cost were not measured. There is no Ollama monthly-film measurement in this evidence, so the hosted film table cannot establish an end-to-end local-versus-hosted speedup.

The [merged report](https://github.com/sam-dumont/immich-memories/blob/ba5b96e53f38ec35a9d8b92f15c6c15b8f232bcc/docs/research/2026-10-03-ollama-validation.md) and [CSV](https://github.com/sam-dumont/immich-memories/blob/ba5b96e53f38ec35a9d8b92f15c6c15b8f232bcc/docs/research/2026-10-03-ollama-validation.csv) preserve all four configurations and the larger probes. Remaining issues are tracked in [#1918](https://github.com/sam-dumont/immich-memories/issues/1918).

## JSON contract regression

The baseline exposed a missing request mode in occasion discovery: sequence readings, holiday checks and special-day decisions asked for JSON in their prompts but omitted `response_format`. The native Ollama adapter also ignored JSON object mode when a caller requested it. [PR #1936](https://github.com/sam-dumont/immich-memories/pull/1936) makes those contracts explicit and preserves ordinary text requests. Tests exercise the production callers with and without the answer bank, plus successive JSON and prose requests through both provider adapters.

Only the annual discovery path in the 14-path baseline sent these occasion requests: 99 calls on OpenAI, 70 on z.ai and 17 on Melious. Other paths keep their baseline measurements. Corrected annual runs and the complete synthetic suite are recorded separately, with their own source revision; the baseline is retained for comparison. The corrected OpenAI trace sent JSON object mode on all 73 occasion requests. z.ai still uses prompt-based JSON on its Anthropic route; its repeat is not a measurement of a new server-side format mode.

Melious's baseline annual run took 1,034.9 seconds and used an estimated €0.19671776. Six responses were empty and truncated. The CLI exited zero but explicitly left unread months for another run. Its coverage check therefore failed. z.ai completed the year with one unjudged day. A zero exit code does not establish a complete catalogue.

| Provider | Baseline elapsed / cost | Corrected elapsed / cost | Corrected HTTP attempts | Empty / truncated answers |
|---|---:|---:|---:|---:|
| OpenAI | 140.5 s / $0.02613340 | 107.4 s / $0.02059800 | 74 | 0 / 0 |
| z.ai | 280.5 s / $0.01656465 | 264.1 s / $0.01612110 | 65 | 0 / 0 |
| Melious | 1034.9 s / €0.19671776 | 1425.5 s / €0.15198184 | 15 | 3 / 4 |

Corrected OpenAI and z.ai logged no unread months or unjudged days. Melious still left unread months: 1,425.5 seconds, €0.15198184, three empty answers and four truncated answers. All 15 requests used JSON object mode. Reasoning consumed 142,095 of 142,435 reported output tokens. The contract fix does not resolve this provider limitation.

Annual repeats used the same prepared seed and fresh editorial decisions. Cache state and provider behavior can change; these single repeats do not isolate a causal speedup.

## Response modes and routes

All three configs set `llm.enabled: true`, `thinking: low` and `structured_output: null`. Each feature selected its own structured or free-text request. The historical Melious global `structured_output: false` override was removed for this run.

| Provider | Configured base URL | Wire dialect | Observed mode behavior |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | Chat Completions | JSON schema/object and free text; automatic token-limit/temperature negotiation |
| z.ai | `https://api.z.ai/api/anthropic` | Anthropic Messages, selected by the production preset | Prompt JSON validated by the feature parser; free text for text contracts |
| Melious | `https://api.melious.ai/v1` | Chat Completions compatible | Schema refusal adapted to JSON object mode; free-text requests kept their own mode |

Returned model identifiers matched the configured identifiers. Scores check production feature results, including the app's normal validation and bounded recovery; they are not unassisted model ratings. Raw request/reply evidence, without HTTP credentials, stays private.

The common `thinking: low` setting does not imply identical wire settings. OpenAI requests used `reasoning_effort: none` for bulk work and `medium` for the title path; z.ai requests used `thinking.type: low`. Melious bulk requests carried `reasoning_effort: low`. Token ceilings followed the production client's normal reasoning-budget and recovery policy. Hosted reader concurrency retained its automatic value of four, the request timeout was 300 seconds, and asynchronous batch delivery was off.

## Motion controls

Five separate production motion requests used right, left, up, down and stationary fixtures. They are additional controls, excluded from the 34-case score and cost above.

| Provider | Passed | Failed directions |
|---|---:|---|
| OpenAI | 2/5 | Right, left, down |
| z.ai | 3/5 | Up, down |
| Melious | 2/5 | Left, down, stationary |

Melious invented movement on the stationary fixture. The same provider passed the main suite's right-moving control but failed other directions. These results retain the [#1650 limitation](https://github.com/sam-dumont/immich-memories/issues/1650).

## Production paths

All 42 production slots are accounted for, including blocked and incomplete attempts. Four discarded setup attempts, 102 baseline synthetic cases, 102 corrected synthetic cases, three corrected annual runs and 15 motion controls remain separate: **268 measurement rows**.

[CSV](./2026-10-03-hosted-readers.csv) and [validated JSON](./2026-10-03-hosted-readers.data.json) contain per-path time, requests, reported tokens, cache reads, empty/truncated/invalid structured answers, cost and outcome flags. Raw prompts, replies and personal media remain private. Token totals were independently checked against the app's counters; price arithmetic and image boundaries were audited.

A path is a user operation, not one model request: annual discovery reads months sequentially, then judges candidate days. Each cell below gives CLI elapsed time, estimated API cost and observed outcome. “Completed” means the command finished; it is not a semantic endorsement. Blocked rows carry partial cost. “Possible” and “thin” are the app’s dry-run pool assessments.

| Path | OpenAI | z.ai | Melious |
|---|---|---|---|
| Monthly film | 77.3 s; $0.00964; 60.8 s film / 15 pictures | 119.9 s; $0.01256; 60.9 s film / 15 pictures | 180.2 s; €0.06631; 60.9 s film / 15 pictures |
| Monthly overviews | 40.3 s; $0.04332; completed | 114.8 s; $0.03171; completed | 226.9 s; €0.16824; completed |
| Year occasion discovery | 140.5 s; $0.02613; completed | 280.5 s; $0.01656; completed | 1034.9 s; €0.19672; incomplete; semantic check failed |
| Synthetic caption producer | 5.0 s; $0.00036; caption passed | 6.1 s; $0.00026; caption passed | 4.0 s; €0.00093; caption passed |
| Request A: dry run | 141.6 s; $0.00133; possible | 150.5 s; $0.00085; dry run completed | 190.2 s; €0.02313; possible |
| Request B: dry run | 123.3 s; $0.00151; possible | 163.2 s; $0.00102; possible | 201.2 s; €0.01932; possible |
| Request C: dry run | 24.6 s; $0.00202; thin | 59.5 s; $0.00077; possible | 150.9 s; €0.00878; possible |
| Request D: dry run | 109.3 s; $0.00155; possible | 112.6 s; $0.00092; possible | 236.4 s; €0.01715; possible |
| Request E: dry run | 119.1 s; $0.00089; thin | 125.3 s; $0.00056; thin | 176.6 s; €0.00518; thin |
| Request A: film | 538.2 s; $0.03068; 294.2 s film / 77 pictures | 733.4 s; $0.02166; 293.2 s film / 77 pictures | 1409.0 s; €0.11927; 293.2 s film / 77 pictures |
| Request B: film | 314.8 s; $0.00484; 66.2 s film / 14 pictures | 1132.8 s; $0.05051; 291.0 s film / 71 pictures; semantic check failed | 2779.9 s; €0.42164; 294.6 s film / 71 pictures |
| Request C: film | 178.2 s; $0.00154; blocked | 75.6 s; $0.00157; 8.5 s film / 1 picture; semantic check failed | 286.0 s; €0.01095; blocked |
| Request D: film | 215.2 s; $0.00145; blocked | 277.0 s; $0.00250; 49.0 s film / 10 pictures | 487.5 s; €0.03392; 49.0 s film / 10 pictures |
| Request E: film | 237.4 s; $0.00128; 10.0 s film / 1 picture | 258.6 s; $0.00073; 10.0 s film / 1 picture | 597.7 s; €0.00824; 10.0 s film / 1 picture |

The paths are a monthly film, monthly overviews, annual occasion discovery, captioning, five free-text dry runs and their five films. Request A through E preserve the same private case identities across providers. The historical caption command would have sent personal images, so path 4 instead calls the production caption producer with a generated red rectangle. It checks that producer's answer, not the historical personal-day CLI.

Each provider received a separate copy of the prepared store and measured-picture caches. Editorial answers, refusals, votes and overviews were cleared before each path. Compatible captions and numeric facts were reused. New local head, detector and clip-frame inference was limited to 1,024 distinct pictures per path; normal metadata and preview reads continued. New personal-image captions and remote preparation were blocked. A missing caption therefore leaves a partial attempt, not a completed cheap film. There was no new full-year preparation or hardware matrix.

The baseline paths and replacement films use a serial queue on the shared Apple M5 Max. Corrected annual replays and validation checks overlapped with other work on that host. These are observed waits, not isolated throughput measurements. The Full tier uses the validated local picture models and `laya-mlx 0.2.0`. That checkpoint warns that one confidence bucket is uncalibrated. ACE-Step was installed and model downloads were disabled. Earlier films, including all three monthly examples, fell back to bundled music because weights were unavailable offline. Generated music was observed in OpenAI Request A, Request B; Melious Request B, Request D, Request E. Other completed films used bundled music. Cache availability changed during the shared-host session; the long-film timings therefore do not all have identical music conditions. Generation is not a music-quality pass. All 15 completed films passed full audio/video decoding. Decode checks and sampled frames do not replace the owner's review of the cut.

OpenAI and Melious Request C films stopped at the 1,024-picture local-preparation bound. OpenAI Request D stopped because a required prepared caption was missing; no new personal-image caption was requested. These are partial attempts. OpenAI Request B produced only 66.2 seconds from 14 pictures, versus 71 pictures in the longer z.ai and Melious outputs, so its lower cost does not establish equivalent coverage.

The paired Request C traces expose unstable interpretation. OpenAI's dry run narrowed a broad scoped pool to three pictures through an extra subject filter; its initial film attempt kept the broad pool before hitting the setup guard. z.ai did the reverse: a broad pool in the dry run, then two pictures in the film request. The resulting 8.5-second, one-picture film does not establish the requested coverage. These are independent readings of the same request after clearing the app's answer bank, not reuse of the dry-run answer.

The z.ai Request B film passed decoding, but many of its 12 evenly spaced sampled frames fell outside the requested subject. Its sampled semantic check failed. Request A's sample was broadly consistent with its subject, with an ambiguous shot; it remains unapproved. The report records review scope; the CSV keeps semantic outcomes separate from HTTP status and the synthetic contract scores. An empty `semantic_pass` cell means no semantic pass was established; `False` records a failed check. Both can accompany a successfully rendered file; failed checks still consume API usage.

Elapsed time measures the CLI work after isolated profile setup and harness imports. Where the app records a root run span, `app_end_to_end_seconds` includes its startup and complete run. `provider_request_seconds` sums the app's model-call wall-time counters, including dispatch, negotiation and failed calls. It is client-side wall time, not provider compute time. Parallel calls can make that sum exceed elapsed time; it cannot be subtracted from elapsed time to derive local processing time.

The input library already had captions and measured picture facts. Prices cover the hosted reader after that preparation. Library ingest, electricity, storage and network charges are excluded. A hosted reader removes the need to serve the text model yourself; local selection, picture classifiers and rendering still contribute to the wait. These Mac measurements do not forecast rendering time on a NAS. A first library preparation, with missing captions or model downloads, is also outside the priced examples.

An uncached-equivalent price uses the same reported token counts with the cache discount removed. It is a pricing counterfactual, not a second measured cold run. The CSV also retains discarded setup attempts separately so their requests and reported-token costs remain visible. The accepted OpenAI monthly run followed a discarded attempt without the Laya runtime; 40,576 input tokens were cache reads. Its latency is therefore not a cold-start measurement. The three early OpenAI free-text films stopped by the overly strict local-preparation guard are also retained separately from their replacement attempts.

## Attempt accounting

Reported-token cost totals below include blocked and failed attempts within each named group. Baseline synthetic and motion rows remain separately priced in the CSV. These are list-price estimates, not account bills.

| Provider | 14 production slots | Discarded setup attempts | Corrected suite and annual replay |
|---|---:|---:|---:|
| OpenAI | $0.12654472 | $0.01916160 | $0.03026140 |
| z.ai | $0.14218445 | $0.00000000 | $0.02228190 |
| Melious | €1.09977036 | €0.00000000 | €0.18370760 |

Across all 268 rows, including setup and repeat runs:

| Provider | HTTP 200 | HTTP 400 | Cancelled | Timeouts | Empty / truncated / invalid explicit JSON answers |
|---|---:|---:|---:|---:|---:|
| OpenAI | 608 | 35 | 0 | 0 | 0 / 0 / 0 |
| z.ai | 622 | 0 | 1 | 0 | 0 / 0 / 0 |
| Melious | 479 | 20 | 0 | 0 | 18 / 29 / 7 |

HTTP 400 responses include normal mode/parameter negotiation. Cancellation does not establish zero provider work; responses without usage remain unpriced. Empty, truncated and invalid-JSON counts overlap. Explicit JSON syntax counts cover requested JSON modes; prompt-only JSON on the Anthropic route is checked by feature validation instead.
