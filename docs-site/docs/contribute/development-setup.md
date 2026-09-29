---
sidebar_label: "Development Setup"
---

# Development setup

The full contribution guidelines are in [CONTRIBUTING.md](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/CONTRIBUTING.md).

You need Python 3.11+, FFmpeg, [uv](https://docs.astral.sh/uv/) and GNU Make. The web UI also
needs Node 22: a checkout builds its own client (see [The web client](#the-web-client)).

```bash
git clone https://github.com/sam-dumont/immich-video-memory-generator.git
cd immich-video-memory-generator
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
| `make dev-mac` | dev + `all-mac` (Apple Vision, Metal, the editorial stack) | Apple Silicon, full feature set |
| `make dev` | every declared extra (torch, demucs, editorial) and the built web client, slow | Only if you work across all optional backends |

**Rendering with generated music on a Mac? Also run `make install-acestep`.** None of the targets
above install ACE-Step: it lives in a sibling `.venv-acestep` next to the checkout, so **every new
clone and every git worktree needs its own `make install-acestep`**. Without it, a config with
`ace_step.mode: lib` renders every film with a bundled track and one warning in the log.
`immich-memories preflight` shows a **Music (ACE-Step)** warning when it is missing, and
`make check-local-audio` proves the install end to end. Details: [Generated music](../better/music.md#install-locally-on-a-mac).

## Check the install

`make check` runs lint, format check, type check, the file length and complexity gates, and the
unit tests. If it passes, your setup is correct. `make ci` adds everything else and is what you run
before opening a PR: if it passes locally, CI will pass too. Both depend on `ensure-dev`, which
syncs every extra, so a run of either turns a `make dev-test` environment into a `make dev` one.

`make help` lists every target. Never run `ruff`, `pytest` or `mypy` directly: the make targets
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
cd web && npm run dev   # the Vite dev server, with hot reload
make web-build          # rebuild the client after a change, as the app serves it
make web-check          # type-check, check the API contract and types, build, refuse Immich logos
```

The build lands in `src/immich_memories/web/client/`, which git ignores, so two web PRs never
conflict on hashed file names again. A wheel can't be built without it: `hatch_build.py` refuses
one and names `make web-build`. `make build` builds the client first.

The client talks to the app through `/api/v1`. After changing an endpoint, run `make web-api`: it
regenerates the OpenAPI document and the client's TypeScript types from it, and `make web-check`
fails while they are stale.

## Merging and releasing

PRs are squash-merged. Before merging a large integration branch, preserve its individual
commits on a `history/` branch. Pick a name for that integration and date, then run this from
the branch being merged:

```bash
git push origin HEAD:refs/heads/history/my-integration-2026-09-15
```

Link that branch in the PR before squashing. Keep the archive when deleting the working branch.

Merging to `main` does not publish a release. The maintainer opens **Actions → Release → Run
workflow**, selects `main`, and chooses the version bump. `auto` reads conventional commits,
including `!` and `BREAKING CHANGE:` markers in the squash message. Select **Dry run** to build
the candidate package without publishing tags, images, packages or docs.

A real release runs CI, builds the app images, renders a CPU smoke film in the exact amd64 image,
and publishes the tested multi-architecture image before the GitHub release and PyPI packages.
The package build must also pass before the Git tag is pushed. Release runs execute one at a time.

CI uses `make secret-scan` for both PRs and release runs: all commits since the latest version
tag, or all history for the first release. It also catches secrets removed by a later commit in
that range. Install Gitleaks 8.24.3 to run the same scan locally; pre-commit uses that version too.

## Private terms gate

`make privacy-gate` blocks owner-defined private terms (family names, birth dates, GPS
coordinates) from diffs, commit messages and PR titles. Two pre-commit hooks run it as well.

The denylist never lives in this repo. It resolves from, in order: `--terms-file`, an env var named
by `--terms-env` (how CI reads the `PRIVATE_TERMS` secret), `$IMMICH_MEMORIES_PRIVATE_TERMS` (a
path), or `~/.config/immich-memories/private-terms.txt`. One term per line, `#` comments ignored, a
`re:` prefix for a regex. With none of those configured the gate prints a notice and exits clean,
which is the normal case for a contributor. Matches are masked to their first character, so a hit
report never contains the term it found.

## Project structure

```
src/immich_memories/
  api/          # Immich API client
  analysis/     # Story-first selection (the editorial route)
  store/        # The annotation store: every banked fact and reading
  triage/       # The pinned ONNX encoder and its eight context heads
  people/       # The people graph and the companion file
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

[ARCHITECTURE.md](https://github.com/sam-dumont/immich-video-memory-generator/blob/main/ARCHITECTURE.md)
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
