---
title: Text reader and provider contracts
---

# Text reader and provider contracts

For the working local and hosted recipes, start with [Add a text reader](../better/reader.md). This reference covers the audience classifier and provider transport. The selection reader receives text; image captions require a separate explicit choice.

## Reader operating modes

`advanced.llm.enabled` defaults to `false`. With it enabled, an empty `base_url` selects the app-owned llama.cpp process; a nonempty URL selects an external server. The default local model is `gemma-4-E4B-it-Q4_0`. For the install recipe, use [Add a reader](../better/reader.md).

```yaml
advanced:
  llm:
    enabled: true
    base_url: ""
    model: gemma-4-E4B-it-Q4_0
    local_server: llama-server
    local_context: 32768
```

Owned inference supports Linux and macOS. `models fetch` downloads the pinned default GGUF and projector when this local reader is configured. A custom `model` names a GGUF path; `local_mmproj` supplies its projector. Preflight checks the executable and files without loading the model.

The app loads the owned reader on demand and waits for active requests before stopping it to release memory for local ACE-Step or Demucs. At the render boundary, selection also closes its Laya scorer, stops the owned reader and clears unused local-runtime buffers. The next reader call loads it again. Cancellation waits for native audio work to finish or time out before releasing its memory lease. An external server owns its own model lifetime: the app cannot assume it is safe to unload it for other clients.

```bash
immich-memories capabilities
immich-memories capabilities --verify-local
```

`--verify-local` uses synthetic inputs and installed weights to check the configured owned reader and local audio path. It does not certify external services or a complete film, and cannot be combined with `--test-music`, which may download models.

## The Laya audience pre-screen

Laya answers the sharing question locally: does the caption describe
a bath, a nappy change, breastfeeding or one of the other
private activities a family film holds back. Laya is a 0.4B text classifier (Apache-2.0),
fine-tuned on captions of public CC BY photographs whose authors are credited in the archive. It
reads the ingest caption, in about 14 ms a shot on Apple silicon. It works with the rules reader
and the prose reader when preparation produces captions. The `gpu` and `full` tiers enable it;
the default `nas` tier uses the picture classifiers and rules.

```bash
pip install laya-mlx                         # Apple Silicon only
immich-memories models fetch --laya          # platform-specific, digest-pinned
```

`models fetch` chooses the Apple archive on Apple silicon and the portable ONNX archive on
Linux, Windows and Intel Macs. ONNX needs the `editorial` extra for CPU or `editorial-cuda` for
NVIDIA. The Apple download is 811 MB. The ONNX download is 877 MB and expands to 1.70 GB;
its calibrated default threshold is
0.185, while MLX keeps 0.186. Both archives are SHA-256 checked. A download mirror must keep the
archive's filename. When configuring a checkpoint for a different backend manually, set its
threshold explicitly too.

The GPU and Full product tiers enable Laya automatically. A saved `laya_audience` value cannot
override the resolved tier. Fetch the checkpoint and check the services with `immich-memories preflight`.

It only adds holds. The detector holds (the sensitive-content detector and the uncovered-person
head) apply first and are never lifted, its findings go through the same support checks as the
reader's, and a shot it doesn't answer stays held to the family. Sharing never asks the prose
LLM, including when Laya is absent or a detector flags exposure. The MLX threshold,
`laya_audience_threshold: 0.186`, kept every hold of its public calibration split. Its known gap:
a travel or administrative document (a boarding pass, an invoice) can slip
through, since few such captions were in its training data. The detectors stay the floor either way.

To use an extracted ONNX checkpoint, point `advanced.editorial.laya_checkpoint` at the
directory containing `model.onnx`, `model.onnx.data`, `rl_agent_config.json` and `tokenizer/`.
The scorer chooses CUDA when available and otherwise uses CPU. This path needs neither
PyTorch nor MLX.

For the audience ONNX export, set `laya_audience_threshold: 0.185`. This threshold was
chosen on the public calibration split to retain all 15 MLX holds. On 3,143 held-out
captions it retained all 23 MLX holds and added one. These are classifier checks; validation
of the complete NVIDIA image is tracked in
[#1385](https://github.com/sam-dumont/immich-video-memory-generator/issues/1385).

## Providers and dialects

Five provider values, three code paths. `ollama` speaks Ollama's native API, `anthropic` speaks
`/v1/messages`, and `openai-compatible` and `openai` speak `/v1/chat/completions`, so anything
serving that endpoint works: mlx-vlm, oMLX, vLLM, Ollama's compatibility layer, Groq, OpenAI
itself. `zai` is the `anthropic` adapter with z.ai's URL and reasoning level filled in, and it is
the one provider that picks its adapter from the `base_url` path, because z.ai serves both dialects
on one host: `.../api/anthropic` gets `/v1/messages`, `.../api/paas/v4` gets `/chat/completions`.

Set `base_url` explicitly for every external server, including hosted providers. An empty URL selects owned local inference regardless of the provider name. The named providers supply their reasoning dialect where settings retain their defaults; explicit request parameters take precedence.

The Messages API path is `POST {base_url}/v1/messages` with `x-api-key`,
`anthropic-version: 2023-06-01` and the prompt as one user message. Nothing about it is
Claude-specific: point `base_url` at whoever serves the dialect. Answers come back as a JSON
envelope the app validates itself, and no provider-side JSON mode is used, so a host without one
loses nothing.

```yaml
advanced:
  llm:
    provider: "anthropic"
    model: "claude-sonnet-5"        # or claude-haiku-4-5 for the cheap seat
    api_key: "${ANTHROPIC_API_KEY}"
    thinking: "high"                # disabled | low | high | max | auto
```

That preset handles two things Claude answers HTTP 400 to otherwise: no `temperature` goes out
(from the 4.7 line on, Claude refuses any sampling parameter), and reasoning is asked for as
`thinking: {"type": "adaptive"}` with the level as `output_config.effort`. Bulk calls send
`thinking: {"type": "disabled"}`, because a bulk call at a 140-token cap that reasons comes back with
no answer in it. A model older than that dialect needs the switch written out:
`thinking_params: {thinking: {type: "enabled", budget_tokens: 2048}}`.

```yaml
advanced:
  llm:
    enabled: true
    provider: "zai"
    base_url: https://api.z.ai/api/anthropic
    model: "glm-5.3-flash"
    api_key: "${ZAI_API_KEY}"
    thinking: "low"
```

Set `base_url: https://api.z.ai/api/anthropic` for its Messages API; use the endpoint your account supports. The
other route, `https://api.z.ai/api/paas/v4`, is the OpenAI-compatible one and answers that account
`429 code 1113, Insufficient balance`; set it explicitly if your account is the other kind. The
GLM-5 line refuses `disabled`, so the preset sends `low`.

For any other host serving the Messages API, set `base_url` yourself and use `thinking: "auto"`,
which sends no reasoning field and takes the host's default.

### Reasoning

On a server whose chat template reasons by default, a bulk call reasons through its small token
budget, stops mid-thought and returns nothing parseable. `llm.no_thinking_params` stops that, and
its default is already the Qwen dialect:

```yaml
llm:
  thinking: "disabled"            # default
  no_thinking_params:             # merged into every non-thinking call
    chat_template_kwargs:
      enable_thinking: false
```

A server that reasons only when asked wants `no_thinking_params: {}` instead. `low`, `high` or
`max` switch two calls to reasoning (title generation and the special-day question in
`discover-days`) while everything else stays fast. `thinking_params` carries the fields those calls
send; OpenAI's reasoning models want `{"reasoning_effort": "medium"}` there, which `provider:
openai` fills in. The provider's own switch
is merged in even when you set your own params, and a `thinking` key you write yourself wins.

Ollama has neither chat dialect: its switch is a bare top-level `think`, billed inside
`num_predict`. A load-bearing call gets `think: true`, a bulk call gets no switch at all (a model
without a thinking mode answers `think` with a 400), and a server that reasons unasked is learned
from its first thinking block: every later call then gets 16,384 extra tokens in `num_predict`. An
`extra_params.options.num_predict` you set yourself wins.

A level is a request, not a promise. z.ai's `.../api/anthropic` route answers HTTP 200 to every
setting and then reasons on its own terms, so on that route the reader reads the first `text` block
and skips the reasoning in front of it, asks for 1,024 tokens on top of the caller's cap, and turns
a reply with no `text` block into an error naming the `stop_reason`. A provider's own error `code`
and `message` go into the log line, cut at 300 characters.

## Structured replies

The default selects the mode by request type. Free-text questions, titles and period accounts
request their JSON schemas on local and hosted endpoints. Local episode readings use prompt-only
JSON because oMLX can stall on their nested schema; hosted episode readings retain the schema.
Both modes work against the same endpoint in one process. `advanced.llm.structured_output` can
explicitly enable or disable schemas for that endpoint.

If a provider refuses schema mode and asks for `json_object`, the app retries once in object
mode and carries the schema in the prompt. It remembers that choice for the endpoint and model
for the rest of the process and logs the adaptation once. A refusal of the whole response-format
parameter removes that parameter. An invalid schema or another ordinary HTTP 400 still fails.
For a provider already known to lack schema support, `structured_output: false` skips negotiation.

## Batch mode

Episode readings are independent prompts. Supported external providers can submit them as batches; pricing and completion latency depend on the host. Owned local inference does not use batch APIs.

```yaml
advanced:
  llm:
    batch: "auto"               # off (default) | auto
    batch_min_requests: 8       # below this, asking one at a time is quicker
    batch_max_wait_minutes: 60  # then ask whatever is left in real time
```

It pays on an unattended run (the nightly `auto run`, a `prepare --overviews` over a year) and not
on a run someone is waiting for: a batch is queued work, and "usually within minutes" is not a
promise you want between a click and a film. If it goes wrong you lose the discount and nothing
else. Anything unanswered by `batch_max_wait_minutes`, any line the provider refused and any
answer the parser won't read is asked again in real time.

| Provider dialect | Batch route |
|---|---|
| OpenAI-compatible | `/v1/batches` |
| Anthropic-compatible | `/v1/messages/batches` |
| Ollama native | No batch route |

The endpoint must support the route. A compatibility dialect alone does not establish that it does, and pricing comes from the provider. Owned local inference stays in real time.

The route is probed once before anything is queued. A host that doesn't serve it is asked once,
logs why, and reads in real time for the rest of the run.

## What the software sends

- **Prompts are bounded before they go out**: episode reads at 24,000 characters and 90 pictures a
  page, story synthesis at 32,000, the period account split into pages. The owned reader defaults to a 32k context; context memory also depends on the server and concurrent work.
- **Answers are parsed against the stage's contract.** An answer the contract refuses costs one
  repair round on that call. A moment pick still refused after its repair doesn't end the film:
  those rows get the moments the no-model film would pick, and the story's pick record says why
  (`pick-rules-fallback`).
- **A reply cut off at its token cap keeps what it finished.** The episode readings or period
  accounts it wrote whole are kept, and only the unfinished ones are asked again. An episode asked
  again gets the full 4,000-token ceiling rather than its own estimate.
- **Text only.** No request to the reader carries a picture; a test fails the build if one does.

For endpoint validation, use the provider conformance checks below. Record usage and timings
separately from the quality of a finished film; [measurement guidance](performance-evidence.md)
explains the comparison.

## Provider conformance

From a checkout, run:

```bash
make llm-conformance CONFIG=/path/to/provider.yaml OUTPUT=/tmp/llm-conformance
```

The command reads only `advanced.llm` (or `llm`) from that file. It sends synthetic evidence
through production features and can incur provider charges. Free-text cases also read the
public WordNet corpus installed by `immich-memories models fetch`. Each banked feature gets a
fresh temporary SQLite store. The suite opens no personal library or people file.

The 34 probes cover occasion, trip and people titles; free-text reading, linking and pool
selection; occasion discovery; music mood; image captions and motion; full and lean episode
readings; month and year accounts; editorial grouping, weighting, picking and recurring
activities; and both audience text readers still present in the code.

Each row reports whether the provider was called, HTTP attempts, reported tokens, elapsed
seconds, validity and a feature-specific quality check. Unknown usage is shown as unknown.
A local fallback fails the check. A failed feature leaves its row and the other checks continue.
The command exits with status 1 if a feature fails or a production model call site has no case.
The guard test scans the code for model calls and shared prompt adapters; runtime observation
also checks that each case reached its declared call sites.

`OUTPUT` is optional. When set, it receives an incremental JSON report, a Markdown table,
and private request/reply evidence without HTTP headers. Keep these files private: provider
errors can include account details. Use the input, cached-input and completion token counters
with the provider's rates to calculate cost. A run with missing usage gives only a cost floor.

Use the report to compare passes, failures, call counts and reported-token cost for your endpoint.
[Measure your setup](performance-evidence.md#cost-and-quality) explains what to record.

These checks measure the configured endpoint on small fixtures. They do not replace checking
the quality of a complete film or testing asynchronous batch delivery.
