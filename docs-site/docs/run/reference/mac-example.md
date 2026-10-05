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

{/* diagram: deploy-mac */}

This path works on Apple Silicon with Metal and VideoToolbox; see
[measured examples](../../better/measured.md#generated-native-mac) for real numbers. That check
didn't activate the reader or generate music; the Full and optional music steps below need their
own configuration checks.


## Install the app

For a source checkout, install uv, `ffmpeg-full`, exiftool and Node 22 first. Use Python 3.12 if you plan to add
local ACE-Step. From your release checkout:

```bash
brew install uv ffmpeg-full exiftool llama.cpp
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
ffmpeg -hide_banner -filters | grep zscale
git clone https://github.com/sam-dumont/immich-memories.git
cd immich-memories
git checkout YOUR_RELEASE_TAG
make dev
make dev-mac
uv pip install --python .venv/bin/python laya-mlx
uv run --no-sync python -c "import pi_heif, laya_mlx"
```

Replace `YOUR_RELEASE_TAG` with the release tag you intend to run. The Mac extras install the
Metal bindings, but **not `laya-mlx`**. The extra install above supplies the audience classifier
used by GPU and Full. `pi-heif` is already a base dependency for HEIC decoding. Keep the FFmpeg
PATH export in your shell startup file and in the environment used to launch a service.

After changing checkout revisions, rerun `make dev-mac` and the `laya-mlx` install before
starting the app. Copying source into an older environment does not update dependencies.
The `--no-sync` commands below preserve that separately installed runtime; an explicit sync
may require installing it again. [Development setup](../../contribute/development-setup.md) covers source tools;
the [requirements page](../requirements.md) covers memory and supported platforms.

Set your Immich connection in Settings or a [small config file](../config-file.md#quick-start-config).
Keep the normal `tier: auto` setting. Start the
[local caption server](../../reference/caption-service.md#apple-silicon-with-llamacpp) in another
terminal, using its pinned model and `smolvlm2-500m-base-public` alias. The llama.cpp recipe used
less resident memory on the 16 GiB M2 smoke host. An existing mlxcel service is a separate process;
stop it when replacing it, otherwise both models remain loaded. For an app on this same Mac,
bind the caption server to `127.0.0.1`.

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
uv run --no-sync immich-memories models fetch
uv run --no-sync immich-memories preflight -v
uv run --no-sync immich-memories config show tier
uv run --no-sync immich-memories ui --host 127.0.0.1
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
