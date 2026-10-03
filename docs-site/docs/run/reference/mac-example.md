---
title: Apple Silicon with local services
description: Run the app, a local reader and captions natively on a Mac, with optional generated music.
---

import DeploymentDiagram from '@site/src/components/DeploymentDiagram';

# Apple Silicon with local services

Run natively to use the Mac's Metal GPU. This setup keeps the app, captions and text reader on one
Mac; Immich can live elsewhere on your network. For a packaged install without local music
generation, use the [Python install](../uv-pip.md).

<DeploymentDiagram topology="mac" />

The [generated native Mac check](../../better/measured.md#generated-native-mac) completed a
19-second film on an M5 Max with Metal and VideoToolbox. It used an isolated candidate wheel,
warm model weights and an existing caption server. That GPU check did not activate the reader
or generate music; the Full and optional music steps below need their own configuration checks.


## Install the app

For a source checkout, install uv, FFmpeg and Node 22 first. Use Python 3.12 if you plan to add
local ACE-Step. From your release checkout:

```bash
git clone https://github.com/sam-dumont/immich-video-memory-generator.git
cd immich-video-memory-generator
git checkout YOUR_RELEASE_TAG
make dev
make dev-mac
brew install llama.cpp
```

Replace `YOUR_RELEASE_TAG` with the release tag you intend to run. The Mac extras install the
Metal bindings. [Development setup](../../contribute/development-setup.md) covers source tools;
the [requirements page](../requirements.md) covers memory and supported platforms.

Set your Immich connection in Settings or a [small config file](../config-file.md#quick-start-config).
Keep the normal `tier: auto` setting. Start the
[local caption server](../../reference/caption-service.md#apple-silicon-with-mlxcel) in another
terminal, using its pinned model and `smolvlm2-500m-base-public` alias. For an app on this same Mac,
bind that server to `127.0.0.1` rather than the recipe's LAN bind.

## Connect captions and the reader

```yaml
advanced:
  editorial:
    preparation:
      caption_base_url: http://localhost:8092/v1
  llm:
    enabled: true
    base_url: ""
```

The blank reader URL uses the app-owned local llama.cpp model. It starts when needed and releases
its model before local music, stems and rendering. You do not need a second reader server.
If you already use one, configure its URL and served model name using
[the reader guide](../../better/reader.md#use-an-existing-server).

Fetch the model files required by this configuration, then check it:

```bash
uv run immich-memories models fetch
uv run immich-memories preflight -v
uv run immich-memories config show tier
uv run immich-memories ui --host 127.0.0.1
```

Open `http://localhost:8080` and make [your first film](../../get-started/first-film.mdx).
Automatic selection can use the native Metal preparation runtime; Full also needs the enabled
reader, captions and Laya ready. Preflight names any missing requirement. A Docker container on
a Mac cannot use Metal directly; this recipe runs outside Docker.

## Optional local music

Bundled or chosen music works without another model. To generate tracks locally, stop the app
and install the separate audio environment in this checkout:

```bash
make install-acestep
make check-local-audio
```

Then add:

```yaml
advanced:
  ace_step:
    enabled: true
    mode: lib
    model_variant: turbo
    use_lm: false
```

Restart the app. This smaller profile needs about 7 GB free for resident weights and 6 GB on disk;
generation needs working memory too. [Generated music](../../better/music.md#local-on-a-mac)
and the [audio runtime](../../reference/local-audio.md#memory-and-disk) cover larger profiles,
checks and fallback reporting. Each checkout or worktree needs its own audio installation.

## Access from another machine

Keep the explicit localhost app bind for a private desktop setup. To reach it from another
machine, choose [authentication](../authentication.mdx) and a
[network/proxy configuration](../network-security.md) first. Local caption routes have no
built-in authentication; only broaden their bind address when another trusted app needs access.
