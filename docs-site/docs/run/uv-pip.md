---
title: uv / pip
---

# uv or pip

For a Mac or Linux machine without Docker. You need Python 3.11 to 3.13 and FFmpeg on your `PATH`.
The [Docker install](./docker.md) is the other option.

## Install

Any FFmpeg build with the `zscale` filter works. On a Mac, start with Homebrew's plain package:

```bash
brew install uv ffmpeg
ffmpeg -hide_banner -filters | grep zscale
```

If that prints a `zscale` line, keep this FFmpeg. If it prints nothing, install the fuller build:

```bash
brew install ffmpeg-full
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
ffmpeg -hide_banner -filters | grep zscale
```

Keep that PATH entry in `~/.zprofile` if you need `ffmpeg-full`. A command run over SSH does not
read that file unless you start a login shell, for example
`ssh host "zsh -l -c 'immich-memories preflight'"`. Check `zscale` in the shell that will run the app.

On Debian/Ubuntu, install FFmpeg with `sudo apt install ffmpeg` and run the same filter check.

Install the package that matches this documentation build. Choose the command for your platform:

import InstallationFiles from '@site/src/components/InstallationFiles';

<InstallationFiles kind="native" />

The command pins `--python 3.12` on purpose. The package supports Python 3.11 and newer, but the
GPU title renderer (`quadrants`) is only installed below 3.14. Without the pin, `uv` picks the
newest Python on your `PATH` (Homebrew's default is 3.14 now), the install succeeds, and titles
quietly fall back to PIL without SDF effects: preflight shows "Title rendering: WARNING PIL + FFmpeg".
If you already installed that way, reinstall with `--force --python 3.12`. With pip, create the
virtual environment from Python 3.11, 3.12 or 3.13.

Pre-tag rehearsals install a published wheel directly from their GitHub release; they are not
uploaded to PyPI. RC/final commands pin the matching PyPI version. No source checkout or local
wheel build is part of either route. A preview without published assets cannot supply this install.
For pip, use the same pinned package specification inside the app's virtual environment.

A bare install lacks the ONNX runtime needed for picture classifiers and for the speech detector
(FireRedVAD, bundled in the package). Without it, a video's cut is still chosen from its picture and
its loudness, but may start or end mid-sentence. The same model also detects a clip's own music or
singing; without the ONNX runtime, the soundtrack never steps aside for it.

The command above includes `--with laya-mlx` on Apple Silicon. Only GPU and Full use it: on Basic
you can drop that part. For GPU or Full, keep it (or append `--with laya-mlx` to the versioned
`uv tool install` command). `all-mac` supplies the Metal bindings but does not include this audience-classifier
runtime. With pip, install `laya-mlx` using the same virtual environment as the app. Downloading
its checkpoint with `models fetch` does not install the Python runtime. See the
[Mac recipe](./reference/mac-example.md#install-the-app) for checkout commands.

`pi-heif`, the HEIC decoder, is a base dependency. If an existing installation cannot import it,
reinstall or sync the selected application version with the same extras before testing another
film. An old environment with new source files is not an updated install.

`uv tool install` puts the command in `~/.local/bin`. If it warns that this folder is not on your
`PATH`, run `uv tool update-shell` and open a new terminal. The terminal you ran it in still
cannot find `immich-memories`: add it for the current shell with
`export PATH="$HOME/.local/bin:$PATH"`. Do the same in a non-login SSH shell. If you run with a
different home directory, use the installed command's absolute path; changing the home does not
move the uv installation.

Create the folder, then `~/.immich-memories/config.yaml`:

```bash
mkdir -p ~/.immich-memories
```

```yaml
tier: basic
immich:
  url: http://192.168.1.10:2283
  api_key: your-api-key
```

The file holds the key, so keep it private: `chmod 600 ~/.immich-memories/config.yaml`. The app
warns at startup when other users can read it.

Create the key in Immich's **Account Settings > API Keys** with the
[ten read permissions](./docker.md#the-api-key). Add the upload set only if you send films back
to Immich. Leave **All** unchecked.
Then:

```bash
immich-memories models fetch
immich-memories preflight
immich-memories ui
```

Open [http://localhost:8080](http://localhost:8080) (`immich-memories ui -p 8081` if 8080 is taken) and make [your first film](../get-started/first-film.mdx).
The guides on the Docker route (Quick start, first film, after install) show `docker compose exec -T immich-memories` in front of every command: leave that prefix off and run `immich-memories ...` directly.
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
On Linux aarch64, `all` and `all-mac` skip `demucs`: its `sphn` dependency ships no wheel there and
needs Rust plus a C compiler to build. Vocal separation shows unavailable instead of installing.
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

### macOS and an Immich on your network

macOS blocks a program from reaching other machines on your local network until you allow it, and your NAS is one of them. `curl` and the browser are exempt, which makes this confusing: `curl` reaches Immich while a scheduled `immich-memories` gets `No route to host` (errno 65). The permission belongs to the interpreter the job runs, the Python in your virtual environment or uv's managed `python3.12` (something like `~/.local/share/uv/python/cpython-3.12.x-macos-aarch64-none/bin/python3.12`), not to Terminal. Allowing Terminal, or running a command there, grants nothing to the 09:00 job.

`immich-memories auto install` checks this for you when your Immich is on a private address. It starts a temporary LaunchAgent that runs the same launcher the schedule runs, with `config test` (it only pings Immich), waits up to 20 seconds, removes the agent, and prints a pass or a fail. If macOS asks whether Python may find devices on your local network, click **Allow**, then run `auto install` again. Run the check while you are at the Mac so you can answer. A failed check can also mean a wrong config, an invalid key or an unreachable server: check `immich-memories config test` before changing permissions. For a Local Network denial without a prompt, check the interpreter in **System Settings > Privacy & Security > Local Network**. An Immich on the internet or on `localhost` is never blocked, so nothing is checked.

If the check failed and you have not run **Activate**, remove the pending installation with
`immich-memories auto install --uninstall` alone. There is no loaded schedule to deactivate.

A Python upgrade can change the interpreter identity and require another Local Network approval. `immich-memories auto status` says when the interpreter is no longer the one that was checked: run `auto install` again at the Mac.

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
