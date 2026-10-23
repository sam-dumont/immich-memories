---
title: Text reader and provider contracts
---

# Text reader and provider contracts

The working local and hosted recipes are in [Add a text reader](../better/reader.md). This page covers what the app sends to a provider, how it adapts to each one, and the Laya audience classifier. The selection reader only ever receives text; sending images takes a separate, explicit choice.

## Reader operating modes

`advanced.llm.enabled` defaults to `false`; a model, URL or key alone never enables it. Enabled with an empty `base_url` and `openai-compatible` or `ollama`, the app runs its own llama.cpp process; a URL points it at an external server. The default local model is `gemma-4-E4B-it-Q4_0`.

```yaml
advanced:
  llm:
    enabled: true
    base_url: ""
    model: gemma-4-E4B-it-Q4_0
    local_server: llama-server
    local_context: 32768
```

The owned reader runs on Linux and macOS. `models fetch` downloads the pinned default GGUF and its projector when it is configured. A custom `model` names a GGUF path, and `local_mmproj` its projector. Preflight checks the executable and the files without loading the model.

The app starts the owned reader on demand and stops it, once active requests finish, to free memory for local ACE-Step or Demucs. When selection hands over to rendering it also closes its Laya scorer, stops the owned reader and clears unused runtime buffers; the next reader call starts it again. The owned reader serves one request at a time, whatever `reader_concurrency` says. Docker and Kubernetes need an external server: the app image has no `llama-server`. The app never unloads an external server's model, since other clients may be using it.

```bash
immich-memories capabilities
immich-memories capabilities --verify-local
```

`--verify-local` runs the owned reader and the local audio path on synthetic inputs with the installed weights. It doesn't check external services or a whole film, and can't be combined with `--test-music`, which may download models.

### Local server defaults {#use-an-existing-server}

For an external `openai-compatible` server, the app classifies the `base_url` host. Loopback,
private IP addresses and single-label service names count as local: one request at a time, with
prompt-only episode JSON and a repetition penalty of 1.0. A dotted hostname counts as hosted:
four concurrent requests, episode schemas on and no repetition penalty. For a LAN server with a
dotted name, set `reader_concurrency: 1`, and `structured_output: false` if its constrained
decoding stalls (that turns schemas off for every request, not only episode readings).

### When the reader stops answering

A reader that stops answering (connection refused, DNS failure, timeout, or a 5xx its retries
couldn't wait out) gets one warning per endpoint:

```text
Reader unreachable at <endpoint> (…); falling back to rules and default wording
```

The app then stops asking it for the rest of the run, still reads answers it already banked,
and the film goes on: the polish ships the rules draft, a model-planned film is planned again by
the rules, and titles use default wording. A rejected key, a missing model or a refused payload
is a configuration error and still stops the run.

## The Laya audience pre-screen

Laya answers the sharing question locally: does the caption describe a bath, a nappy change,
breastfeeding or another private moment a family film holds back? It is a 0.4B text classifier
(Apache-2.0), fine-tuned on captions of public CC BY photographs whose authors are credited in
the archive, and reads a shot's caption in about 14 ms on Apple silicon. The `gpu` and `full`
tiers turn it on, with no separate switch, and it works with both the rules reader and the model
reader. `basic` has no captions, so it uses the picture classifiers and rules.

```bash
uv tool install --python 3.12 "immich-memories[all-mac]" --with laya-mlx  # Apple Silicon uv-tool install
immich-memories models fetch --laya          # platform-specific, digest-pinned
```

No app extra includes `laya-mlx`. In a checkout, use
`uv pip install --python .venv/bin/python laya-mlx`; with pip, run
`python -m pip install laya-mlx` with the app's Python. A system-wide `pip install` doesn't reach
a `uv tool` environment. Without the runtime, sharing says it is using the heads and rules alone.

`models fetch` chooses the Apple archive on Apple silicon and the portable ONNX archive on
Linux, Windows and Intel Macs. ONNX needs the `editorial` extra for CPU or `editorial-cuda` for
NVIDIA.

| Archive | Download | Default threshold |
|---|---|---|
| Apple (MLX) | 811 MiB (851 MB) | 0.186 |
| Portable (ONNX) | 836 MiB (877 MB), about 1.70 GB unpacked | 0.185 |

Both are SHA-256 checked, and a download mirror must keep the archive's file name. If you point
the setting at the other backend's checkpoint by hand, set its threshold too. Then run
`immich-memories preflight`.

Laya only adds holds. The detector holds (the sensitive-content detector and the uncovered-person
head) apply first and are never lifted, its findings go through the same support checks as the
reader's, and a shot it doesn't answer stays held to the family. Sharing never asks the prose
LLM, even when Laya is missing or a detector flags exposure. The MLX threshold, 0.186, kept
every hold of its public calibration split. A travel or administrative document (a boarding
pass, an invoice) can slip through, since few such captions were in its training data; the
detectors stay the floor either way.

To use an extracted ONNX checkpoint, point `advanced.editorial.laya_checkpoint` at the
directory containing `model.onnx`, `model.onnx.data`, `rl_agent_config.json` and `tokenizer/`.
The scorer chooses CUDA when available and otherwise uses CPU. This path needs neither
PyTorch nor MLX.

The ONNX threshold, 0.185, was chosen on the same public calibration split to keep all 15 MLX
holds. On 3,143 held-out captions it kept all 23 MLX holds and added one. Those are classifier
numbers, not a judgement on whole films.

## Ollama

Native Ollama uses `/api/generate`. For Gemma 4 E4B, set the context in `options`
and explicitly disable thinking for the text reader:

```yaml
advanced:
  llm:
    enabled: true
    provider: ollama
    base_url: http://localhost:11434
    model: gemma4:e4b-it-q4_K_M
    extra_params:
      think: false
      options:
        num_ctx: 32768
```

Pull it with `ollama pull gemma4:e4b-it-q4_K_M`; the explicit tag is the quantization that
was tested. `extra_params.think: false` turns thinking off on every native request, titles
included. Without it, thinking can eat the first large episode request's token budget and cut
the JSON answer short. Leave it out only if you want reasoning and give it the tokens.

For Ollama's OpenAI route, use its own reasoning switch:

```yaml
advanced:
  llm:
    enabled: true
    provider: openai-compatible
    base_url: http://localhost:11434/v1
    model: gemma4:e4b-it-q4_K_M
    no_thinking_params:
      reasoning_effort: none
```

That route cannot set the context per request. Start the server with
`OLLAMA_CONTEXT_LENGTH=32768 ollama serve`, or create a model with
`PARAMETER num_ctx 32768` in its Modelfile. The default
`chat_template_kwargs.enable_thinking: false` does **not** disable thinking on
Ollama's compatible route. See [Ollama context length](https://docs.ollama.com/context-length)
and [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility).
From a container, use the host's reachable address instead of `localhost`.

Both recipes passed the larger episode and story-selection probes on an M5 Max, with Gemma 4
E4B only. [Measure your setup](../better/measured.md#local-reader-time-and-accuracy) has the
per-check results.

## Providers and dialects

Five provider values, three code paths. `ollama` speaks Ollama's native API, `anthropic` speaks
`/v1/messages`, and `openai-compatible` and `openai` speak `/v1/chat/completions`, so anything
serving that endpoint works: mlx-vlm, oMLX, vLLM, Ollama's compatibility layer, Groq, OpenAI
itself. `zai` is the `anthropic` adapter with z.ai's URL and reasoning level filled in, and it is
the one provider that picks its adapter from the `base_url` path, because z.ai serves both dialects
on one host: `.../api/anthropic` gets `/v1/messages`, `.../api/paas/v4` gets `/chat/completions`.

`openai`, `anthropic` and `zai` fill a blank `base_url` with `https://api.openai.com/v1`,
`https://api.anthropic.com` and `https://api.z.ai/api/anthropic`. Any other external server
needs an explicit URL; a blank `openai-compatible` or `ollama` URL means the owned local reader.
The named providers fill in their reasoning dialect where you left the defaults; parameters you
set yourself win.

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

z.ai sells two kinds of account. The Messages route above works for one; the other uses the
OpenAI-compatible route, `https://api.z.ai/api/paas/v4`, which answers the wrong kind of account
with `429 code 1113, Insufficient balance`. Set the URL your account supports. The GLM-5 line
refuses `disabled`, so the preset sends `low`.

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

By default the mode follows the request. Free-text questions, titles and period accounts send
their JSON schemas to every endpoint. Episode readings on an external local server get the shape
in the prompt instead, because oMLX can stall on their nested schema; the owned llama.cpp reader
and hosted endpoints keep the schema. `advanced.llm.structured_output` forces it on or off for
the endpoint.

Occasion discovery, holiday checks and special-day decisions request JSON object mode.
Native Ollama receives `format: "json"` for these calls. Plain-text requests do not inherit
that mode from an earlier decision.

If a provider refuses schema mode and asks for `json_object`, the app retries once in object
mode and carries the schema in the prompt. It remembers that choice for the endpoint and model
for the rest of the process and logs the adaptation once. A refusal of the whole response-format
parameter removes that parameter. An invalid schema or another ordinary HTTP 400 still fails.
For a provider already known to lack schema support, `structured_output: false` skips negotiation.

## Batch mode

Episode readings are independent prompts, so a provider with a batch API can take them as one
batch. Price and turnaround are the host's. The owned local reader never batches.

```yaml
advanced:
  llm:
    batch: "auto"               # off (default) | auto
    batch_min_requests: 8       # below this, asking one at a time is quicker
    batch_max_wait_minutes: 60  # then ask whatever is left in real time
```

It pays on an unattended run (the nightly `auto run`, a `prepare --overviews` over a year), not
on a run someone is waiting for: a batch is queued work, and "usually within minutes" is not what
you want between a click and a film. If it goes wrong you lose the discount, nothing else. Anything unanswered by `batch_max_wait_minutes`, any line the provider refused and any
answer the parser won't read is asked again in real time.

| Provider dialect | Batch route |
|---|---|
| OpenAI-compatible | `/v1/batches` |
| Anthropic-compatible | `/v1/messages/batches` |
| Ollama native | No batch route |

Speaking a dialect doesn't mean serving its batch route. The app probes the route once before
queueing anything; a host that doesn't serve it logs why and is read in real time for the rest of
the run.

## What the software sends

- **Prompts are bounded before they go out**: episode reads at 24,000 characters and 90 pictures a
  page, story synthesis at 32,000, the period account split into pages. The owned reader
  defaults to a 32,768-token context.
- **Answers are parsed against the stage's contract.** An answer the contract refuses costs one
  repair round on that call. A moment pick still refused after its repair doesn't end the film:
  those rows get the moments the no-model film would pick, and the story's pick record says why
  (`pick-rules-fallback`).
- **A reply cut off at its token cap keeps what it finished.** The episode readings or period
  accounts it wrote whole are kept, and only the unfinished ones are asked again. An episode asked
  again gets the full 4,000-token ceiling rather than its own estimate.
- **The selection reader receives text only.** Image captions use the same settings only with an explicit [LLM-caption opt-in](../better/captions.md#explicit-llm-captions).

To check an endpoint, run the conformance suite below. Keep usage and timings apart from the
quality of a finished film; [Benchmarking your own setup](performance-evidence.md) explains
how.

## Provider conformance

From a checkout, run:

```bash
make llm-conformance CONFIG=/path/to/provider.yaml OUTPUT=/tmp/llm-conformance
```

The command reads only `advanced.llm` (or `llm`) from that file. It sends synthetic evidence
through production features and can incur provider charges. Free-text cases also read the
public WordNet corpus installed by `immich-memories models fetch`. Each banked feature gets a
fresh temporary SQLite store. The suite opens no personal library or people file.

The 37 probes cover occasion and trip titles; free-text reading, linking and pool
selection; occasion discovery; music mood, quiet and lively; image captions and motion; full and
lean episode readings; month and year accounts; the film summary; editorial grouping, weighting,
picking and recurring activities; and both audience text readers still present in the code.

Each row reports whether the provider was called, HTTP attempts, reported tokens, elapsed
seconds, validity and a feature-specific quality check; usage the provider didn't report shows
as unknown. A local fallback fails the check. A failed feature keeps its row and the others still
run. The command exits 1 if a feature fails or a production model call site has no case: a guard
scans the code for model calls, and each case must reach the call sites it declares.

`OUTPUT` is optional. When set, it receives an incremental JSON report, a Markdown table,
and private request/reply evidence without HTTP headers. Keep these files private: provider
errors can include account details. Use the input, cached-input and completion token counters
with the provider's rates to calculate cost. A run with missing usage gives only a cost floor.

Use the report to compare passes, failures, call counts and reported-token cost for your endpoint.
[Benchmarking your own setup](performance-evidence.md#cost-and-quality) explains what to record.
[Measure your setup](../better/measured.md#hosted-reader-time-and-cost) records tested endpoints,
elapsed time, token costs and quality limits, including the motion-direction weak spot.

These checks run small fixtures. They don't test batch delivery, and they don't replace
watching a whole film.
