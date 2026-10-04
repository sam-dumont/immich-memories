---
sidebar_label: "Development Setup"
---

# Development setup

The full contribution guidelines are in [CONTRIBUTING.md](https://github.com/sam-dumont/immich-memories/blob/main/CONTRIBUTING.md).

You need Python 3.11 to 3.13, FFmpeg, [uv](https://docs.astral.sh/uv/) and GNU Make. The web UI
also needs Node 22: a checkout builds its own client (see [The web client](#the-web-client)). On
3.14, `uv sync` installs fine but skips the GPU title renderer (`quadrants` has no wheel for it
yet): pin the checkout's virtualenv with `uv venv --python 3.12` before `make dev-test`.

```bash
git clone https://github.com/sam-dumont/immich-memories.git
cd immich-memories
make dev-test
```

`make dev-test` is `uv sync --extra dev --locked`: the dev tools (pytest, ruff, mypy and the other
CI gates) and nothing else. No torch, no CUDA, and it is what the CI test jobs install. There is no
`gpu` extra to add: the GPU title kernels are a base dependency wherever they publish a wheel. Run
it before any other make target.

| Target | Installs | When |
|--------|----------|------|
| `make dev-test` | dev tools only | Default for contributors (what CI tests with) |
| `make dev-ci` | dev tools only | Identical to `dev-test` today |
| `make dev-mac` | dev + `all-mac` (Apple Vision, Metal, the editorial stack) | Apple Silicon app dependencies; Laya and ACE-Step need the installs below |
| `make dev` | CPU `all` + `mac` + `dev`, and the built web client; includes torch and demucs | Only if you work across all optional backends |

For CUDA editorial development on Linux, use `uv sync --extra dev --extra editorial-cuda`.
Do not combine it with `editorial`, `all` or `all-mac`: CPU and GPU ONNX distributions
share an import namespace, and uv refuses these combinations. `--all-extras` is therefore
unsupported. When running `check` or `ci` in that prepared CUDA environment, set
`ENSURE_DEV_COMMAND=true` so the CPU setup does not replace it.

**GPU or Full on Apple Silicon also needs Laya.** After `make dev-mac`, run
`uv pip install --python .venv/bin/python laya-mlx`. It is not part of `all-mac`.
Use `uv run --no-sync immich-memories ...` to preserve that separately installed runtime;
repeat its install after an explicit environment sync. The [Mac recipe](../run/reference/mac-example.md)
also checks HEIC decoding and the effective FFmpeg build before generation.

**Rendering with generated music on a Mac? Also run `make install-acestep`.** None of the targets
above install ACE-Step: it lives in a sibling `.venv-acestep` next to the checkout, so **every new
clone and every git worktree needs its own `make install-acestep`**. Without it, a config with
`ace_step.mode: lib` renders every film with a bundled track and one warning in the log.
`immich-memories preflight` shows a **Music (ACE-Step)** warning when it is missing, and
`make check-local-audio` proves the install end to end. Details: [Generated music](../reference/local-audio.md#local-runtime-and-repairs).

## Households and cultures

Changes for different families, households and celebrations are welcome. An issue is enough to start; you don't have to write code.

Give an anonymized example: who belongs to the household, which people or dates matter, what the app does now, and what you expected instead. For holidays, include the country or culture and how the date is determined. Made-up names and synthetic pictures are fine. Please keep API keys, birth dates and private photos out of public issues.

Help me check the result against your example. Inclusive labels alone don't prove the selection, people groups, titles or calendar behave correctly. Once we have a reproducible case, it can become a regression test.

## Check the install

`make check` runs lint, format check, type check, the file length and complexity gates, and the
unit tests. If it passes, your setup is correct. `make ci` adds everything else and is what you run
before opening a PR: passing locally catches the checks you can reproduce before CI. Both depend on `ensure-dev`, which
syncs the same CPU extras as `make dev`, so either adds the heavy optional packages to a `make dev-test` environment. On Linux, demucs pulls torch and NVIDIA wheels even though ONNX stays on the CPU variant. To keep a prepared lightweight environment, set `ENSURE_DEV_COMMAND=true` explicitly.

`make help` lists common targets; the Makefile contains the full list. Never run `ruff`, `pytest` or `mypy` directly: the make targets
match what CI runs, so local results are consistent. Use
[conventional commit](https://www.conventionalcommits.org/) messages.

The test tiers, what each needs, and what to do when diff-cover fails on your PR are in the
[Testing guide](./testing.md).

## The web client

The web UI is a SvelteKit client in `web/` at the repository root, built into the Python package
and served by the app at `/app`. The built client is not committed: the release wheel and the
Docker image build it, and a checkout builds its own. `make dev` does it for you. After
`make dev-test`, run `make web-client` once (Node 22, what CI uses). Until then `/app` says the
client is not built and names the command.

```bash
make web-client         # npm ci, then build the client into the package
make web-build          # rebuild the client after a change, as the app serves it
make web-check          # type-check, check the API contract and types, build, refuse Immich logos
```

For hot reload, run the development server separately from the repository root:

```bash
npm --prefix web run dev
```

The build lands in `src/immich_memories/web/client/`, which git ignores, so generated hashed filenames stay out of source control. A wheel can't be built without it: `hatch_build.py` refuses
one and names `make web-build`. `make build` builds the client first.

The client talks to the app through `/api/v1`. After changing an endpoint, run `make web-api`: it
regenerates the OpenAPI document and the client's TypeScript types from it, and `make web-check`
fails while they are stale.

## Release process

Maintainers use the [release workflow](./releasing.md). It covers candidate promotion, image-only publishes and the private terms gate.

## Project structure

```text
src/immich_memories/
  api/          # Immich API client
  analysis/     # Story-first selection (the editorial route)
  store/        # The annotation store: every banked fact and reading
  db/           # The store's engine, tables, migrations, backup and restore
  triage/       # The pinned ONNX encoder and its eight context heads
  people/       # The people graph and registry
  photos/       # Photo-to-video animation
  processing/   # Video assembly (FFmpeg)
  titles/       # Title screens, map fly-overs
  audio/        # Music generation, audio ducking
  web/          # The web server: /api/v1, sign-in, health (the Svelte client is web/ at the repo root)
  cli/          # Click commands
  cache/        # Thumbnail, judgment and embedding caches
  tracking/     # Run history
  operations/   # Lifecycle phases, storage report
  planning/     # Auto-duration planning
  automation/   # auto suggest/run
  memory_types/ # Preset system
```

[ARCHITECTURE.md](https://github.com/sam-dumont/immich-memories/blob/main/ARCHITECTURE.md)
has the full module map with class relationships.

## Interface translations

Web client labels use `t('Text')` from `web/src/lib/i18n.svelte.ts`. For inserted values, keep a
named placeholder in the template: `t('Connected as: {name}', {name: username})`. Mark labels
stored in tables with `N_('Text')`, then translate them with `t` where they are shown.

Run `make ui-catalogues` after changing labels. It reads the literal first argument of every `t`
and `N_` in `web/src` and updates `ui.po` beside each language's film-text `messages.po`,
preserving translations and leaving new messages for translation. The app serves the same
catalogues to the client at `/api/v1/i18n`.
Keep placeholders and their format specifications intact. The catalogue test checks every
supported language for missing messages and mismatched placeholders. Non-English catalogues
are marked AI-drafted until reviewed; native-speaker corrections are welcome.

The app reads the shipped PO files directly and caches them. No separate compilation step is
needed. Restart the app after editing a catalogue.

<span id="images-without-a-release"></span>
<span id="release-candidates"></span>
<span id="private-terms-gate"></span>

<span id="merging-and-releasing"></span>

Merging and releasing are covered in the [release workflow](./releasing.md).
