---
title: Text reader and provider contracts
---

# Text reader and provider contracts

For the working local and hosted recipes, start with [Add a text reader](../better/reader.md). This reference covers the audience classifier and provider transport. The selection reader receives text; image captions require a separate explicit choice.

## Reader operating modes

`advanced.llm.enabled` defaults to `false`; a model, URL or key alone never enables it. With it enabled, an empty `base_url` with `openai-compatible` or `ollama` selects the app-owned llama.cpp process; a nonempty URL selects an external server. The default local model is `gemma-4-E4B-it-Q4_0`. For the install recipe, use [Add a reader](../better/reader.md).

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

The app loads the owned reader on demand and waits for active requests before stopping it to release memory for local ACE-Step or Demucs. At the render boundary, selection also closes its Laya scorer, stops the owned reader and clears unused local-runtime buffers. The next reader call loads it again. Cancellation waits for native audio work to finish or time out before releasing its memory lease. The owned reader always serves one request at a time (`reader_concurrency` cannot increase it). Docker and Kubernetes need an external server; the app image has no `llama-server`. An external server owns its own model lifetime: the app cannot assume it is safe to unload it for other clients.

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
uv tool install "immich-memories[all-mac]" --with laya-mlx  # Apple Silicon uv-tool install
immich-memories models fetch --laya          # platform-specific, digest-pinned
```

`laya-mlx` is not included in an app extra. In a checkout, use
`uv pip install --python .venv/bin/python laya-mlx`; with pip, run
`python -m pip install laya-mlx` using the app's Python. A bare system `pip install` does not
add it to a `uv tool` environment. Without the runtime, sharing reports that heads and rules
are being used alone.

`models fetch` chooses the Apple archive on Apple silicon and the portable ONNX archive on
Linux, Windows and Intel Macs. ONNX needs the `editorial` extra for CPU or `editorial-cuda` for
NVIDIA. The Apple download is 811 MiB (851 MB). The ONNX download is 836 MiB (877 MB)
and expands to about 1.70 GB;
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
captions it retained all 23 MLX holds and added one. These are classifier checks. The NVIDIA runtime and image work is recorded in the closed
[#1385](https://github.com/sam-dumont/immich-video-memory-generator/issues/1385); the counts
here measure classifier holds, not end-to-end film performance.

## Ollama

Native Ollama uses `/api/generate`. Set the context in `options`:

```yaml
advanced:
  llm:
    enabled: true
    provider: ollama
    base_url: http://localhost:11434
    model: gemma4:e4b
    extra_params:
      options:
        num_ctx: 32768
```

For Ollama's OpenAI route, use `provider: openai-compatible` and `base_url: http://localhost:11434/v1`. That route cannot set the context per request. Start the server with `OLLAMA_CONTEXT_LENGTH=32768 ollama serve`, or create a model with `PARAMETER num_ctx 32768` in its Modelfile. See [Ollama context length](https://docs.ollama.com/context-length) and [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility#setting-the-local-context-size). From a container, use the host's reachable address instead of `localhost`.

## Providers and dialects

Five provider values, three code paths. `ollama` speaks Ollama's native API, `anthropic` speaks
`/v1/messages`, and `openai-compatible` and `openai` speak `/v1/chat/completions`, so anything
serving that endpoint works: mlx-vlm, oMLX, vLLM, Ollama's compatibility layer, Groq, OpenAI
itself. `zai` is the `anthropic` adapter with z.ai's URL and reasoning level filled in, and it is
the one provider that picks its adapter from the `base_url` path, because z.ai serves both dialects
on one host: `.../api/anthropic` gets `/v1/messages`, `.../api/paas/v4` gets `/chat/completions`.

`openai`, `anthropic` and `zai` fill a blank `base_url` with `https://api.openai.com/v1`,
`https://api.anthropic.com` and `https://api.z.ai/api/anthropic`, respectively. Set an explicit URL for other external servers. Blank `openai-compatible` or `ollama` uses an owned local reader. The named providers supply their reasoning dialect where settings retain their defaults; explicit request parameters take precedence.

The Messages API path is `POST {base_url}/v1/messages` with `x-api-key`,
`anthropic-version: 2023-06-01` and the prompt as one user message. Nothing about it is
Claude-specific: point `base_url` at whoever serves the dialect. Answers come back as a JSON
envelope the app validates itself, and no provider-side JSON mode is used, so a host without one
loses nothing.

```yaml
advanced:
  llm:
    enabled: true
    provider: "anthropic"
    model: "claude-haiku-4-5"
    api_key: "${ANTHROPIC_API_KEY}"
    thinking: "auto"
```

Start with `thinking: "auto"`: it omits both reasoning switches and uses the model's default. Haiku 4.5 does not accept adaptive thinking. Sonnet 5.5, Opus 5.5 and Fable models reject `thinking: {type: "disabled"}`. The app's other thinking levels use adaptive thinking for titles and send the disabled switch on bulk calls; use those only with a model that accepts both. See [Anthropic's thinking matrix](https://platform.claude.com/docs/en/build-with-claude/thinking).

The preset drops `temperature`. An explicit `budget_tokens` override alone does not remove the preset's adaptive effort field. Keep `thinking: "auto"` unless you have checked every custom field against your model's contract.

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
`max` switch title generation to reasoning while other calls use the non-thinking policy.
`thinking_params` carries the fields that title call sends; OpenAI's reasoning models want `{"reasoning_effort": "medium"}` there, which `provider:
openai` fills in. The provider's own switch
is merged in even when you set your own params, and a `thinking` key you write yourself wins.

Ollama has neither chat dialect: its switch is a bare top-level `think`, billed inside
`num_predict`. A load-bearing call gets `think: true`, a bulk call gets no switch at all (a model
without a thinking mode answers `think` with a 400), and a server that reasons unasked is learned
from its first thinking block: every later call then gets 16,384 extra tokens in `num_predict`. An
`extra_params.options.num_predict` you set yourself wins.

A level is a request, not a promise. z.ai's `.../api/anthropic` route answers HTTP 200 to every
setting and then reasons on its own terms, so on that route the reader reads the first `text` block
and skips the reasoning in front of it, asks for 16,384 tokens on top of the caller's cap, and turns
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
- **The selection reader receives text only.** Image captions use the same settings only with an explicit [LLM-caption opt-in](../better/captions.md#explicit-llm-captions).

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
[Measure your setup](performance-evidence.md#cost-and-quality) explains what to record. The
[contract-fix follow-up](../better/measured.md#llm-contract-fixes) records the tested endpoints
and the remaining motion and story-ranking limitations.

These checks measure the configured endpoint on small fixtures. They do not replace checking
the quality of a complete film or testing asynchronous batch delivery.
