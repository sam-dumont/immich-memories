---
title: Native Mac or Linux
description: Install Basic, GPU or Full natively, with packaged releases and local services.
---

import InstallationFiles from '@site/src/components/InstallationFiles';
import SetupBuilder from '@site/src/components/SetupBuilder';

# Native Mac or Linux

Run the app directly on your machine. Apple Silicon uses Metal for GPU and Full; Docker on a
Mac cannot use Metal. Linux can run Basic locally or use a separate NVIDIA inference service.
You need Python 3.11–3.13 and FFmpeg with the `zscale` filter.

## Apple Silicon {#apple-silicon}

Choose **Basic**, **GPU** or **Full** below and enter your Immich address. The builder provides
the package command, configuration and service commands for that tier.

- **Basic:** the app and local classifiers, with no separate model server.
- **GPU:** the app uses Metal; the commands also start the local caption server and install Laya.
- **Full:** adds the app-owned local reader. Leave its URL blank for that default, or enter your
  existing reader's URL and served model name. Allow memory for it alongside the app and captions.

<SetupBuilder initialPlatform="mac" showPlatform={false} />

Save the generated config at the path shown in the commands, replace the API-key placeholder
with your [scoped Immich key](./docker.md#the-api-key), then run the remaining commands.
When preflight passes, open the localhost URL and make [your first film](../get-started/first-film.mdx).
Keep the terminal running while using the app.

## Linux or Intel Mac {#install}

### 1. Install the package

On Debian/Ubuntu, install FFmpeg with `sudo apt install ffmpeg`. On an Intel Mac:

```bash
brew install uv ffmpeg
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed, then use the
Linux / Intel Mac command below. It installs Python 3.12 and the packaged app:

<InstallationFiles kind="native" />

### 2. Connect Immich and choose the tier

Create `~/.immich-memories/config.yaml`:

```bash
mkdir -p ~/.immich-memories
```

```yaml
tier: basic
immich:
  url: http://192.168.1.10:2283
  api_key: your-api-key
```

Use the [ten read permissions](./docker.md#the-api-key) and keep the file private with
`chmod 600 ~/.immich-memories/config.yaml`.

For **GPU**, first start [the NVIDIA inference and caption worker](./reference-setup.md#one-gpu-service).
Set `tier: gpu` and add its endpoints:

```yaml
advanced:
  inference:
    facts_base_url: http://192.168.1.50:8092
  editorial:
    preparation:
      caption_base_url: http://192.168.1.50:8092/v1
```

Keep the worker on a trusted private network. The app also needs its Laya runtime and checkpoint;
`models fetch` prepares the checkpoint and preflight checks both.
For **Full**, set `tier: full` and add an enabled [reader](../better/reader.md) under the same
`advanced` section (keep the inference and caption entries above):

```yaml
  llm:
    enabled: true
    provider: openai-compatible
    base_url: http://192.168.1.50:8000/v1
    model: your-server-model-name
```

Use a server with 32k context and add `api_key` if required. Configure it before starting Full. A local reader needs `llama-server` on
PATH; an external reader needs its URL, served model and any API key.

### 3. Prepare and start

```bash
immich-memories models fetch
immich-memories preflight
immich-memories ui --host 127.0.0.1
```

Open [http://localhost:8080](http://localhost:8080) and make
[your first film](../get-started/first-film.mdx). Films default to `~/Videos/Memories`.
Commands in other guides use a Docker prefix; here run `immich-memories ...` directly.

## Access from another machine {#reaching-the-ui-from-another-machine}

Keep the localhost bind for a private desktop install. Configure [authentication](./authentication.mdx)
before listening on the network. [Network and security](./network-security.md) covers proxies and HTTPS.

## After the first film

Set [home and people](../get-started/who-is-who.md), keep a
[backup](./maintenance/storage-backups.md), or enable [automatic films](../make/automate.md).
[Upgrading](./maintenance/upgrading.md#uv--pip) preserves the installed extras and app data.

## Installation details

[Python installation details](./reference/python-install.md) covers runtime extras, FFmpeg/PATH
problems, pip, source checkouts and native scheduling. [Installation help](../reference/installation-help.md)
covers readiness failures. [Tested deployments](./tested-deployments.md) records platform coverage.

<span id="extras" /><span id="daily-automation" /><span id="macos-and-an-immich-on-your-network" />
<span id="what-to-keep" /><span id="logs-health-and-hardware" /><span id="add-ons" />
<span id="updating" /><span id="from-a-checkout" /><span id="stop-or-remove-this-installation" />

For a deliberate removal, use [Stop, reset and uninstall](./lifecycle.md).
