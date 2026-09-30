---
title: Add a text reader
---

# Add a text reader

A reader writes titles and music mood on any tier. With GPU capability, captions and Laya ready, it also enables **Full**: a refinement of the rules draft. The selection reader receives text, not pictures.

You need a model with at least a **32k context** and an OpenAI-compatible, Anthropic-compatible or Ollama endpoint. The local default used by this project is Gemma 4 E4B. See [tested setups](../run/requirements.md#supported-and-tested) for the limits of that support.

## Local on a Mac

[oMLX](https://github.com/jundot/omlx) serves MLX models on macOS 15+.

```bash
brew tap jundot/omlx https://github.com/jundot/omlx
brew install jundot/omlx/omlx
omlx start
```

Download `mlx-community/gemma-4-e4b-it-6bit` from the server’s admin page at `http://localhost:8000/admin/chat`, then configure the app:

```yaml
advanced:
  llm:
    provider: openai-compatible
    base_url: http://localhost:8000/v1
    model: gemma-4-e4b-it-6bit
```

Use the exact model name returned by `/v1/models`. From Docker Desktop, use `host.docker.internal` instead of `localhost`; from a NAS, use the Mac’s LAN address. Add `api_key` if your server requires a token.

On Linux, vLLM or Ollama can serve the model. Use the matching provider and the endpoint your server exposes. [Provider examples](../reference/llm-providers.md#providers-and-dialects).

## Hosted

Descriptions, dates, people and place names leave your network. If they should stay home, use a local endpoint.

```yaml
advanced:
  llm:
    provider: openai
    model: gpt-4.1-mini
    api_key: ${OPENAI_API_KEY}
```

Hosted presets fill in the provider URL. Existing matching answers are reused. [Measured provider checks](./measured.md) describe tested features and failures; a working API alone does not prove good film choices.

## Check it

```bash
immich-memories preflight
```

The **LLM** row checks the configured model. With `tier: auto`, GPU inference plus a reader selects Full; without GPU inference, selection remains NAS and the reader can still write titles and music mood.

If refinement cannot read the period account after its retry, the rules draft remains and the run reports that refinement did not run. Check the result rather than assuming the model improved it.

## Laya and advanced settings

Laya is the local caption-based sharing classifier enabled by GPU and Full. Install the [platform runtime and checkpoint](../reference/llm-providers.md#the-laya-audience-pre-screen), then check preflight. Sharing never asks the prose reader.

Provider dialects, reasoning, JSON replies, batching and conformance are in the [LLM reference](../reference/llm-providers.md). Explicit image captions are a separate [opt-in](./captions.md#explicit-llm-captions).
