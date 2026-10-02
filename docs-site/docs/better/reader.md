---
title: Add a text reader
---

# Add a text reader

A reader writes titles and music mood on any tier. With GPU inference, captions and Laya ready, it also enables **Full**: refinement of the rules draft. The selection reader receives text, not pictures.

Use a model with a 32k context and valid structured replies. The app can run its local default, or call an API server you already use.

## Let the app run the local model

On native Linux or macOS, install llama.cpp with `llama-server` on your `PATH`. On a Mac:

```bash
brew install llama.cpp
```

On Linux, install a CPU or CUDA build from the [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases), or follow its [build instructions](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md). Put `llama-server` on `PATH`. GPU offload follows the build defaults; the owned process does not accept custom GPU-layer flags.

The published Docker image does not include `llama-server`. Docker and Kubernetes installs need an external reader server. Then enable the reader in your config:

```yaml
advanced:
  llm:
    enabled: true
    base_url: ""
    model: gemma-4-E4B-it-Q4_0
```

Fetch its pinned files before the first request:

```bash
immich-memories models fetch
immich-memories preflight
```

The app starts the model when needed and stops its owned reader before local music, stem separation and rendering. Selection also releases its Laya scorer before rendering. Later requests load the models again. With `enabled: false`, the reader sends no requests and starts no model. Setting a model, URL or API key never enables it. Preflight warns when a reader is configured but disabled. A custom GGUF can replace the default; [local reader settings](../reference/llm-providers.md) cover paths and context size.

## Use an existing server

For oMLX, vLLM, Ollama's compatible API or another `/v1/chat/completions` endpoint:

```yaml
advanced:
  llm:
    enabled: true
    provider: openai-compatible
    base_url: http://192.168.1.50:8000/v1
    model: your-server-model-name
```

Use the exact name the server advertises. From Docker Desktop, `host.docker.internal` reaches a native server on the host; `localhost` reaches the container itself. Add `api_key` when the server requires one. The app treats loopback, private IP addresses and single-label service names as local: one request at a time, with prompt-only episode JSON and a repetition penalty of 1.0. A dotted hostname counts as hosted: four concurrent requests, episode schemas enabled and no repetition penalty by default. For a LAN server with a dotted name, set `reader_concurrency: 1` and `structured_output: false` if its constrained decoding stalls; the latter disables schemas for every request, not just episode readings.

The server manages its own model memory. The app does not unload an external server's models, so account for that memory alongside captions and music.

## Hosted

A hosted reader receives descriptions, dates, people and place names from your cut. Use a local reader if that text should stay home.

```yaml
advanced:
  llm:
    enabled: true
    provider: openai
    model: gpt-4.1-mini
    api_key: ${OPENAI_API_KEY}
```

The provider preset supplies the API URL. Provider names, native Ollama and Anthropic examples, token settings and batching live in the [LLM reference](../reference/llm-providers.md).

## Check the setup

```bash
immich-memories preflight
immich-memories capabilities
```

These report connections, installation and available features; they do not certify the quality of a film. With `tier: auto`, GPU inference plus an enabled reader selects Full. GPU capability includes a remote inference service, a working local CUDA ONNX runtime, or a Mac's Metal GPU. Without these, selection remains NAS and the reader can still write titles and music mood. GPU and Full also require captions and Laya.

Review the result. A failed refinement can leave the rules draft and reports that refinement did not run. [Laya](../reference/llm-providers.md#the-laya-audience-pre-screen) handles caption-based sharing separately; sharing never asks the prose reader.

One `advanced.llm` section supplies titles, the selection reader, music mood, special days and optional LLM captions. Before 1.0, configurations could implicitly enable a reader by naming its model or URL and could use a separate title-model block. These shortcuts are removed: add `enabled: true` and move title settings into `advanced.llm`.

Image captioning with the reader is a separate [opt-in](./captions.md#explicit-llm-captions). That role sends pictures and needs a vision-capable model.
