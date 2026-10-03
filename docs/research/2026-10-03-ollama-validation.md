# Ollama validation on M5 Max, 3 October 2026

Gemma 4 E4B works through Ollama's native and OpenAI-compatible APIs. For the
text reader, explicitly disable thinking using the API's own setting. Changing
only the server URL from oMLX leaves a real configuration gap.

[Issue #1918](https://github.com/sam-dumont/immich-video-memory-generator/issues/1918)
tracks the remaining first-request and answer-quality failures.

## What ran

- Product revision: `a3bfc5dbe66efceaf6985abed72c78600a0fbb37`, frozen before the runs.
- Hardware: Apple M5 Max, 128 GiB unified RAM; Ollama detected Metal.
- Server: official Ollama **0.35.1**, bound to loopback, one parallel request and
  one loaded model, with `OLLAMA_CONTEXT_LENGTH=32768`.
- Model: `gemma4:e4b-it-q4_K_M`, GGUF Q4_K_M. Model digest:
  `dc35e8d9c6061baa6f0fa870975ab6932e2542b579b13ea0f199fa4bb7300c9c`.
- Ollama's loaded-model API confirmed a **32,768-token context**.
- The existing `immich_memories.conformance` command exercised 34 production
  features with synthetic text and generated images. Actual HTTP requests and
  replies were recorded. No provider responses were mocked.
- Separate larger probes reused `scripts/reader_probe_prompts/episodes.txt`
  and `story-pick.txt`, their output budgets and production answer parsers.

This is the same Gemma 4 E4B variant as the previous oMLX validation, with different
quantization: Q4_K_M GGUF here, 6-bit MLX there. SmolVLM2, the M2, real libraries
and end-to-end film rendering were outside this run.

## Complete feature suite

| Route | Thinking control | Passed | HTTP attempts | Summed probe time |
|---|---|---:|---:|---:|
| Native `/api/generate` | Server default | 34/34 | 85 | 318.77 s |
| Native `/api/generate` | `extra_params.think: false` | 33/34 | 85 | 53.01 s |
| Compatible `/v1/chat/completions` | Default app settings | 25/34 | 97 | 345.19 s |
| Compatible `/v1/chat/completions` | `no_thinking_params.reasoning_effort: none` | 32/34 | 85 | 45.04 s |

All 32 text checks and image captioning passed on native Ollama with thinking
disabled. Its only miss was motion direction. The compatible route with thinking
disabled also lost the race from a period summary: 31/32 text checks and image
captioning passed. These remaining failures are answer-quality failures, not
connection failures. The earlier oMLX complete-suite result also missed motion.

The compatible baseline failed age ranges, calendar dates, a particular-place
request, recorded occasion recognition, motion, image captioning, story moment
selection and both audience checks. Its request payload carried the default
`chat_template_kwargs.enable_thinking: false`, but Ollama still returned thinking.
For example, both calendar-date attempts consumed their 300-token limit with
empty answer content and `finish_reason: length`. The corrected switch removed
those empty-answer failures without changing application code.

The native baseline returned thinking on all 85 requests, with no HTTP errors or
truncations in this suite. That result alone concealed the first-request issue below.

## Larger prompts and first-request behavior

| Route | Probe | Result | Seconds |
|---|---|---|---:|
| Native, server default | Episodes | Truncated at 4,000 output tokens | 26.10 |
| Native, server default | Story pick | 8 kept, 0 unused | 16.31 |
| Native, thinking off | Episodes | 22/22 episodes read | 14.78 |
| Native, thinking off | Story pick | 8 kept, 0 unused | 0.59 |
| Compatible, thinking off | Episodes | 22/22 episodes read | 17.33 |
| Compatible, thinking off | Story pick | 8 kept, 0 unused | 0.66 |

The thinking-off requests contained 6,274 and 5,819 input tokens, respectively.
Episode output used 2,509 tokens; the story pick used 83. Both fit the original
4,000- and 300-token limits. Reader preflight also passed for all three configurations.

The native adapter learns to add reasoning headroom after seeing its first thinking
response. Titles ran first in the complete suite, so later requests benefited from
that learned state. In a fresh process, the larger episode request came first and
truncated after returning both thinking and part of the JSON answer. This probe
checks the first response without the higher-level episode repair/retry loop; it
does not establish that a full film would necessarily fail.

The native thinking-off rows above were confirmed in a separate fresh process,
with the original 4,000/300 limits and no learned headroom. The earlier thinking-off
replay also passed; its timings are not substituted into the table. Compatible
thinking-off used its own endpoint state and the original limits.

## Reproduce

Install [Ollama 0.35.1](https://github.com/ollama/ollama/releases/tag/v0.35.1), then:

```bash
ollama pull gemma4:e4b-it-q4_K_M
OLLAMA_CONTEXT_LENGTH=32768 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 ollama serve
```

Native `native.yaml`:

```yaml
advanced:
  llm:
    enabled: true
    provider: ollama
    base_url: http://127.0.0.1:11434
    model: gemma4:e4b-it-q4_K_M
    timeout_seconds: 120
    extra_params:
      think: false
      options:
        num_ctx: 32768
```

Compatible `compatible.yaml`:

```yaml
advanced:
  llm:
    enabled: true
    provider: openai-compatible
    base_url: http://127.0.0.1:11434/v1
    model: gemma4:e4b-it-q4_K_M
    timeout_seconds: 120
    no_thinking_params:
      reasoning_effort: none
```

Run each sequentially from the recorded product revision:

```bash
python -m immich_memories.conformance --config native.yaml --output output/ollama-native
python -m immich_memories.conformance --config compatible.yaml --output output/ollama-compatible
```

A nonzero exit records a failed feature; retain the results table. To reproduce
the baselines, remove `extra_params.think` from the native config and remove
`no_thinking_params` from the compatible config. Ollama documents the compatible
API's [reasoning control](https://docs.ollama.com/api/openai-compatibility) and the
native [thinking field](https://docs.ollama.com/capabilities/thinking).

## Evidence and limits

The [aggregate CSV](2026-10-03-ollama-validation.csv) contains 136 complete-suite
rows and six separate larger-prompt rows. They are not combined into a single
score. Blank token fields mean unreported; Ollama did not report separate
reasoning-token counts. Full request/reply evidence, configs, model metadata and
the larger-probe replay scripts are retained locally under
`output/ollama-validation-2026-10-03/`, outside version control.

The larger-probe replay called the current `query_llm` directly: the older matrix
wrapper still passes the removed `cache_path` argument. Prompts, parsers and
token budgets were reused unchanged. An initial complete-suite launch through
macOS's `/tmp` alias was discarded because the coverage profiler resolves
`/private/tmp`; all scored complete runs used the canonical source path.

Runs were sequential on the same shared Mac, with potentially warm model and
prompt caches. The existing oMLX process remained running and was observed idle
before validation; it received no requests from these tests. Timings include
feature orchestration and retries, not downloads. They do not establish isolated
throughput, a speed ranking against oMLX, M2 behavior or broad film quality.

The existing conformance and LLM transport unit tests also passed: 75 checks.
