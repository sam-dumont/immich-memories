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

The app-owned llama.cpp reader keeps episode JSON schemas enabled; the external-server workaround below does not apply to it.

Use the exact name the server advertises. From Docker Desktop, `host.docker.internal` reaches a native server on the host; `localhost` reaches the container itself. Add `api_key` when the server requires one. Local servers get conservative defaults, hosted-looking (dotted-name) servers get faster ones; tune `reader_concurrency` and `structured_output` if needed. See [local server defaults](../reference/llm-providers.md#use-an-existing-server) for the exact values.

The server manages its own model memory. The app does not unload an external server's models, so account for that memory alongside captions and music.

## Hosted

A hosted reader receives descriptions, dates, people and place names from your cut. Use a local reader if that text should stay home.

See the [measured hosted-reader time and cost](./measured.md#hosted-reader-time-and-cost) for complete
films, free-text requests and provider quality checks. The prices cover reader calls after
picture preparation; the local machine still does selection and rendering.

```yaml
advanced:
  llm:
    enabled: true
    provider: openai
    model: gpt-5.6-luna
    thinking: low
    api_key: ${OPENAI_API_KEY}
```

The provider preset supplies the API URL. Provider names, native Ollama and Anthropic examples, token settings and batching live in the [LLM reference](../reference/llm-providers.md).

## Check the setup

```bash
immich-memories preflight
immich-memories capabilities
```

These report connections, installation and available features; they do not certify the quality of a film. With `tier: auto`, GPU inference plus an enabled reader selects Full. GPU capability includes a remote inference service, a working local CUDA ONNX runtime, or a Mac's Metal GPU. Without these, selection remains Basic and the reader can still write titles and music mood. GPU and Full also require captions and Laya.

Review the result. A failed refinement can leave the rules draft and reports that refinement did not run. [Laya](../reference/llm-providers.md#the-laya-audience-pre-screen) handles caption-based sharing separately; sharing never asks the prose reader.

One `advanced.llm` section supplies titles, the selection reader, music mood, special days and optional LLM captions. Add `enabled: true` and keep title settings in `advanced.llm`.

Image captioning with the reader is a separate [opt-in](./captions.md#explicit-llm-captions). That role sends pictures and needs a vision-capable model.
