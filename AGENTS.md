# Immich Memories: project instructions

Immich Memories turns an Immich library into short films. Claude and Codex write most of the code;
the maintainer sets direction, rules on product questions and judges the films. These are the
standing rules. If one looks wrong for the task in front of you, say so rather than working around
it.

This file is `AGENTS.md`, read by Claude Code, Codex and other coding agents. Topic rules live next
to it: `.claude/rules/testing.md` (tests and source), `.claude/rules/code.md` (Python source) and
`.claude/rules/docs.md` (README and docs site). Claude Code loads each one when you touch matching
files; other agents read the relevant one before changing those files. `ARCHITECTURE.md` maps the
codebase; read it before exploring.

## Releases and versions

The project follows semantic versioning from 1.0.0-rc.1 on. Users install releases and release
candidates, so these are public contracts:

- CLI commands and flags, config keys and their meaning, environment variables;
- the HTTP API (`/api/v1/...`, `/api/trigger`) and web routes;
- the store: migrations are forward-only and automatic, and an upgrade never loses data;
- outputs people script against: film file names, run folders, the `report` format.

Breaking one of these takes a major version. Within a major line, deprecate instead: keep the old
behaviour working with a warning that names its replacement, document it in
`docs-site/docs/run/maintenance/upgrading.md`, and remove it at the next major. A commit that breaks
a contract carries `!` or a `BREAKING CHANGE:` footer so the release workflow bumps the major;
`feat` and `fix` commits are non-breaking by definition.

## Milestones and issues

Every open issue belongs to one milestone, and the maintainer decides what goes into each release.
Milestones are named after what they ship:

- `X.Y.Z-rc.N`: the gate for one release candidate;
- `X.Y.Z`: the release itself. A major or minor release starts with a cleanup pass in its
  milestone (security review, dead code, duplication, complexity hot spots, dependency audit,
  docs drift), done before the last candidate is promoted;
- `Later`: the backlog, organised under epics.

Each milestone has one tracking issue (label `tracking`) that says what the milestone is for and
what "done" means, with its work attached as sub-issues. Opening a milestone means opening its
tracking issue too. The GitHub project "Immich Memories roadmap" shows all of it; issue #326 points
there, so roadmap lists live nowhere else.

When you file an issue, give it a milestone, one type label (`bug`, `enhancement`, `documentation`,
`tests`), at least one `area/*` label, and attach it to its epic or tracking issue as a sub-issue.
Work the current milestone first. Moving an issue into a release milestone is the maintainer's call.

A release candidate is blocked by security problems and by broken or wrong output in flows outside
experimental features. Free-text requests (`--ask`) carry the `experimental` label and never block.
Everything else goes to a later milestone: polish comes after the release.

Before tagging, the advertised features are run for real on a real library, on the exact commit
being tagged, with evidence per feature. Green unit tests are a different check.

## How a change lands

1. An issue describes what and why.
2. Branch from `origin/main` in a worktree outside `/tmp`, with a `feat/`, `fix/`, `docs/`,
   `refactor/` or `build/` prefix. `main` only changes through PRs.
3. Work test-first (see `.claude/rules/testing.md`), running targeted tests while you iterate.
4. Make one commit per PR. Stage everything, then commit once: the pre-commit hook runs the full
   suite and every gate (about 20 minutes), so it is the final check. If it fails, fix and amend.
5. Group related fixes from one area into one PR, each closed with `Fixes #N`. The `#` matters:
   without it GitHub won't close the issue. Fewer PRs means fewer competing for merge slots and
   fewer conflicts. Keep unrelated concerns, such as a refactor next to a fix, in separate PRs.
6. Rebase on `origin/main`, push, open the PR with a conventional title, and enable squash
   auto-merge.
7. Follow the PR until it merges. Poll `gh pr view` and `gh pr checks` in a background loop that
   exits on merge or failure; a `pgrep` loop matches itself and never ends. When `main` moves and
   checks need a rerun, use `gh pr update-branch`. When a check fails, read that step's log and fix
   the cause.

Under the maintainer's standing permission, green PRs merge without a human reading every diff, so
the CI gates are what every change has to pass. A design conflict, or a failing gate that needs a
product ruling, goes to the maintainer instead.

**Working with subagents.** Give each one a complete brief: the issues, these rules, its worktree
path and the one-commit rule. Treat its report as a report, not proof: check the branch and PR
yourself, and wait for anything it left running. Keep at most two or three full-suite commits
running at once, since they share one machine.

**Long runs.** Keep a task list and work through it. Stop to ask only when nothing can move without
the maintainer (a product ruling, an approval for an outward-facing action) or when the next step is
deliberately protected. Status notes are welcome alongside the next action.

## Safety

These rules protect the maintainer's data and the public repository. For Claude Code, a hook in
`.claude/hooks/` enforces the mechanical ones; every agent follows them either way.

- Pass every gate as it is. If a gate is wrong, fix the gate in its own PR and explain why. Commits
  go through the hook (no `--no-verify`, no `SKIP=`).
- Respect `.gitignore`: an ignored file stays out of the repo. Change `.gitignore` itself, in a PR,
  if something should be tracked.
- The maintainer's own data changes only with their explicit approval for that action:
  `~/.immich-memories/` (config, store, people graph), their Immich server (reads are fine; uploads,
  albums and stacks need approval) and their cluster repository.
- Tests run sealed from the real home. The suite seals `HOME` and the store only when `-m` excludes
  integration tests, which `make test` and the default addopts do. Run pytest with the default
  addopts or through a `make` target; a test that writes under `Path.home()` asserts it is sealed
  first.
- Public text (code, tests, commits, PRs, issues, docs) carries no family names, places, asset ids,
  album names, dates that identify people, private hostnames or paths. `make privacy-gate` checks a
  denylist kept outside the repo.
- Errors, logs, reports and tracebacks never print config values. Redact anything read from config
  before printing it, nested account keys included.
- Releases, deploys, posts, mails and deletions in Immich happen only on the maintainer's go for
  that specific action.

## Setup

1. Run `make dev` in every clone and worktree before any other target; it installs the dev tools
   into the project venv.
2. Before rendering with generated music on a Mac, run `make install-acestep`. ACE-Step lives in a
   sibling `.venv-acestep` that each clone and worktree needs; without it every film quietly gets a
   bundled track, and `immich-memories preflight` warns.

## Commands

Use the `make` targets; they are what CI runs. `make help` lists all of them.

| Purpose | Target |
|---|---|
| Unit tests | `make test`; while iterating, `uv run pytest tests/<files>` |
| Integration | `make test-integration`, or one folder, e.g. `make test-integration-assembly` |
| Store on both backends | `make test-store` |
| Launch check, real Immich, built image | `make launch-check-ci`, `make test-immich-gate`, `make test-container` |
| Web client E2E | `make e2e` |
| Style and types | `make lint`, `make format`, `make typecheck` |
| Structure | `make file-length`, `make complexity`, `make cognitive-complexity`, `make dead-code`, `make duplication`, `make arch-check` |
| Security | `make security-lint`, `make semgrep`, `make pip-audit`, `make npm-audit-reviewed-docs`, `make privacy-gate` |
| Docs | `make docs-build`, `make docs-voice`, `make docs-cli-check`, `make docs-config-check`, `make docs-diagrams-check` |
| Everything | `make ci` (what the pre-commit hook and CI run) |
| AI-smell audit | `make critique` |

A new check goes into the Makefile first; CI and the hook call the target.

## Key entry points

- CLI: `src/immich_memories/cli/__init__.py` → `main()`
- Pipeline: `src/immich_memories/analysis/smart_pipeline.py` → `SmartPipeline.run()`
- Assembly: `src/immich_memories/processing/video_assembler.py` → `VideoAssembler.assemble()`
- Web: `src/immich_memories/web/server.py` → `create_app()` (FastAPI); the client is `web/` (SvelteKit)
