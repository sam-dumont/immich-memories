---
title: uv / pip
---

# uv or pip

For a Mac or Linux machine without Docker. You need Python 3.11+ and FFmpeg on your `PATH`.
The [Docker install](./docker.md) is the other option.

## Install

On macOS, install the FFmpeg build with `zscale` for HDR conversion:

```bash
brew install uv ffmpeg-full
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
```

Keep the PATH export in your shell's startup file. On Debian/Ubuntu, install FFmpeg with
`sudo apt install ffmpeg`. Verify HDR support:

```bash
ffmpeg -hide_banner -filters | grep zscale
```

Install the app (quotes matter in zsh):

```bash
uv tool install "immich-memories[all]"
```

On Apple Silicon, use `"immich-memories[all-mac]"`. It includes the Metal bindings; add
`[all-mac,auth]` if you want OIDC. For pip, use the same package spec inside a virtual environment.
For a candidate, use the exact package version published with its application release,
including the same extras. `vX.Y.Z-rc.N` in GitHub corresponds to `X.Y.ZrcN` on PyPI;
that spelling is an example, not evidence that a package exists. Never substitute the latest
stable package when following candidate docs: its CLI and setup may differ.

Check the [application release assets](https://github.com/sam-dumont/immich-memories/releases)
and [PyPI files](https://pypi.org/project/immich-memories/#files) before installation.
A development documentation build has no matching published native package unless its
candidate manifest explicitly supplies one. A wheel built on the tester's machine does not
satisfy the prebuilt first-run gate.

A bare install lacks the ONNX runtime needed for picture classifiers.

Create `~/.immich-memories/config.yaml`:

```yaml
immich:
  url: http://192.168.1.10:2283
  api_key: your-api-key
```

Create the key in Immich's **Account Settings > API Keys** with the
[ten read permissions](./docker.md#the-api-key). Add the upload set only if you send films back
to Immich. Leave **All** unchecked.
Then:

```bash
immich-memories models fetch
immich-memories preflight
immich-memories ui
```

Open [http://localhost:8080](http://localhost:8080) and make [your first film](../get-started/first-film.mdx).
Films default to `~/Videos/Memories`. Set home coordinates for trips and public holidays:
[Home and people](../get-started/who-is-who.md).

## Reaching the UI from another machine

Without authentication, the app binds to localhost. Enabling [Basic auth or OIDC](./authentication.mdx)
makes it listen beyond localhost. To keep an authenticated laptop install local, be explicit:

```bash
immich-memories ui --host 127.0.0.1
```

`--host` overrides the safety default, even with auth off. Enable login before exposing the UI.
For a proxy with HTTPS, use [the proxy checklist](./authentication.mdx#behind-a-reverse-proxy-with-tls).

## Extras

For most installs, use `all` or `all-mac`. Smaller/custom installs:

| Extra | Adds |
|---|---|
| `editorial` | CPU picture classifiers; the minimum for films |
| `editorial-cuda` | CUDA classifiers on Linux; replaces `editorial` |
| `mac` | Apple hardware bindings; not enough on its own |
| `music`, `audio` | Bundled music and local-track metadata |
| `auth` | OIDC login |
| `demucs` | Local music stem separation |

Never install `editorial` and `editorial-cuda` together: both provide `onnxruntime`.
`all` includes editorial/music/audio/auth/demucs. `all-mac` includes the same except auth, plus mac.
Local ACE-Step is a [separate checkout setup](../better/music.md), not a pip extra.

## Daily automation

A laptop's UI is rarely running all day. Install a system schedule:

```bash
immich-memories auto install --hour 9
```

Run the printed `Activate:` command once. The installer uses launchd on macOS, a systemd user
timer on Linux, or a cron command otherwise. On headless Linux, run `loginctl enable-linger "$USER"`. Run **Deactivate:** before `auto install --uninstall`: it removes files without stopping a loaded schedule. For systemd, run `systemctl --user daemon-reload` after removal; for cron, remove the pasted entry.

Keep credentials in `config.yaml`: scheduled jobs do not inherit your interactive shell.
On macOS, a missed run happens after wake; launchd does not wake the machine.
If you run the UI as a permanent service, you can use its built-in daily timer instead.
Use one scheduler. [Automate it](../make/automate.md#bare-metal-auto-install) covers both.

## What to keep

Back up `~/.immich-memories/store.db` with `immich-memories store backup`.
Keep the encryption key too if you save credentials in Settings.
[Database and backups](./database.md) covers restore and PostgreSQL.

## Logs, health and hardware

Logs go to stderr. Use `immich-memories -v ...` for debug output.
[Diagnostics](./maintenance/health-logs-cache.md) covers probes, preflight and log files.
[Hardware encoding](./hardware.md) covers Apple, Intel/AMD and NVIDIA setups.

## Add-ons

Point the app at the services you want: [a reader](../better/reader.md),
[captions](../better/captions.md), [inference](../better/inference.md),
[a render worker](../better/gpu-render.md) or [generated music](../better/music.md).

## Updating

Use [Upgrading](./maintenance/upgrading.md#uv--pip). Keep the same extras when using pip.

## From a checkout

For development, you also need Node 22 to build the web client:

```bash
git clone https://github.com/sam-dumont/immich-memories.git
cd immich-memories
uv sync --extra editorial
make web-client
uv run immich-memories models fetch
uv run immich-memories ui
```

On Apple Silicon, use `--extra all-mac`. Add `--extra auth` for OIDC.
Inside a checkout, use `uv run immich-memories ...`; it does not install a global command.
The published wheel and Docker image already contain the web client.

## Stop or remove this installation

[Stop, reset and uninstall](./lifecycle.md) separates retaining data for reinstall from deleting app state.
