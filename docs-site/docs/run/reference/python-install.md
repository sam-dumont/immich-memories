---
title: "Python installation details"
---

# Python installation details

## Extras

| Extra | What it adds |
|---|---|
| `editorial` | ONNX Runtime and Hugging Face Hub, for the context heads and the two detectors. The one you need |
| `editorial-cuda` | The same on a CUDA host. **Replaces** `editorial`, never joins it |
| `mac` | pyobjc bindings (Quartz, Metal, Vision) for hardware probing. Not enough to cut with alone |
| `music` | The bundled royalty-free track library |
| `auth` | OIDC login (authlib) |
| `demucs` | Local Demucs stem separation for music ducking (Torch, about 80 MB of model) |
| `all` | All of the above except `mac` and `editorial-cuda` |
| `all-mac` | `editorial`, `mac`, `music` and `demucs`. No `auth`: add `[all-mac,auth]` for OIDC |

Never install `editorial` and `editorial-cuda` together: `onnxruntime` and `onnxruntime-gpu` own
the same import name, and the one that answers is whichever pip wrote last.

GPU title rendering needs no extra: its kernel library is a base dependency wherever it publishes a
wheel ([Title kernels](.././hardware.md#title-kernels)). Local ACE-Step music on a Mac is a checkout
job (`make install-acestep`, then `make check-local-audio`): [Generated music](../../better/music.md).

exiftool is worth having on an Apple HEIC library: it is the fallback when the Python HDR headroom
parser trips on an unusual file. `brew install exiftool`, or `apt install libimage-exiftool-perl`.


## From a checkout

```bash
git clone https://github.com/sam-dumont/immich-memories.git
cd immich-memories
uv sync --extra editorial      # or --extra all-mac on Apple Silicon
make web-client                # the web UI, built from web/; needs Node 22
uv run immich-memories ui
```

`uv sync` installs into the clone's `.venv` and puts nothing on your `PATH`: inside the clone it is
always `uv run immich-memories ...`. `pip install -e ".[editorial]"` works too. A checkout is the only install
that needs Node: the PyPI wheel and the Docker image ship the web client already built. Skip
`make web-client` and the CLI still works, but `/app` only tells you to build the client.

## Installation troubleshooting

### Package, Python and FFmpeg

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

Use the versioned package command from [Native installation](../uv-pip.md).

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
[Mac recipe](.././reference/mac-example.md#install-the-app) for checkout commands.

`pi-heif`, the HEIC decoder, is a base dependency. If an existing installation cannot import it,
reinstall or sync the selected application version with the same extras before testing another
film. An old environment with new source files is not an updated install.

`uv tool install` puts the command in `~/.local/bin`. If it warns that this folder is not on your
`PATH`, run `uv tool update-shell` and open a new terminal. The terminal you ran it in still
cannot find `immich-memories`: add it for the current shell with
`export PATH="$HOME/.local/bin:$PATH"`. Do the same in a non-login SSH shell. If you run with a
different home directory, use the installed command's absolute path; changing the home does not
move the uv installation.

Continue with [Connect Immich and choose the tier](../uv-pip.md#2-connect-immich-and-choose-the-tier)
in the native installation guide. If you already completed it, your connection, model files and
output directory are ready; these troubleshooting notes do not require a second setup.


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
