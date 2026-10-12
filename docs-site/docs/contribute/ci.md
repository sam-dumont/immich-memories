---
title: CI and quality gates
---

# CI and quality gates

## CI pipeline

CI runs in tiers, cheap to expensive. A pull request runs only the jobs its changes can break;
a push to `main`, a release and the nightly run every job.

- **Tier 0: change scope and cache setup.** `make ci-scope` (`scripts/ci_scope.py`) sorts the diff
  into areas and every later job reads the answer in its `if:`. Every job that installs the project
  waits on the cache setup.
- **Tier 1: quality gates** (the table below), one job, steps in order, each carrying
  `if: !cancelled()` so the first failure doesn't hide the rest. Commitlint runs on pull requests
  only. A second job runs the security scans in parallel. Both run on every pull request.
- **Tier 2: tests**, after both tier 1 jobs pass. The unit suite (Ubuntu on 3.11/3.12/3.13; macOS on
  3.13 for a pull request, all three on `main` and in a release), each cell in two shards
  (`make test-cov-xml TEST_SHARD=1/2`), plus `make test-extras`. On `main` and in a release the
  macOS cells run whole, one job each, since six macOS shards would queue behind the 5-job macOS cap. Neither extras job pulls torch, so
  what runs there is the subset that survives without it; the rest is a local target. A pull request
  also runs, beside them, one job per FFmpeg integration suite its changed source reaches
  (`make test-integration-<suite>`).
- **Coverage**, once every unit shard passed. The 3.12 Ubuntu shards upload their coverage data;
  `make coverage-combine` merges it, checks the 65% floor on the whole suite and writes
  `coverage.xml`. On a pull request, diff-cover then checks 80% of the changed lines against it
  plus the integration suites' XMLs, and posts the report on the pull request.
- **Tier 3: build**, after tests. Package build, the Docker images and the container e2e job.

The docs build starts immediately. The hermetic launch check and the feature tests start off the
cache setup alone, in parallel shards. The launch check is Playwright e2e against a fake Immich in
two shards per store backend (`make launch-check-ci E2E_SHARD=1/2` on SQLite, and
`make launch-check-ci-postgres` too when the store changed). The feature tests on the fixture
library run in three (`make test-features FEATURE_SHARD=1/3`). The render worker's own suite runs
as a CI job too. `immich-gate.yml` runs the real-Immich gate (v2, 3.2 and v3) and the feature tests
against a real Immich, two shards per major, each seeding its own Immich; scoped the same way.

Shards cost runner slots. A pull request that changes Python runs about 35 jobs across `ci.yml`
and `immich-gate.yml`, and the account runs 20 at once (5 of them macOS), so with a few pull
requests open some jobs wait for a runner, and the wall time grows with the queue.

`scripts/shard_tests.py` deals whole test files to the shards, longest first, by the seconds each
took in that suite (`tests/shard_durations.json`; refresh it with `make shard-durations` after a
full local run), and `tests/test_shard_tests.py` checks that every CI shard set runs every file of
its suite exactly once. With `TEST_SHARD`, `E2E_SHARD` or `FEATURE_SHARD` unset, the targets run
every file. The jobs that serve the web client restore it from a cache keyed on `web/`, so it is
built once per change to the client.

What a pull request runs:

| The diff touches | Runs |
|---|---|
| Only docs (`docs-site/`, `docs/`, `*.md`) | Quality, security, the docs build if `docs-site/` changed, and **Docs Contract Tests**: only the unit tests that read the changed pages. No test matrix |
| A doc page the feature suites read (the upgrading page, for one) | The above plus the launch check and the Immich gate |
| Only tests (`tests/` outside the e2e, feature and gate suites) | Quality, security, the unit suite on the full matrix. No docs build, package, launch check, gate or container job |
| App code (`src/`, `web/`, `packages/`) | The unit suite (full matrix when Python changed, one cell for `web/` alone), package build, launch check, Immich gate; extras and the render worker when it touches what they import |
| The fakes, the seeding or the gate suites (`tests/e2e/`, `tests/integration/immich_gate/`, `tests/integration/features/`, `tests/immich_fakes.py`) | The unit suite, launch check and Immich gate |
| The render worker (`services/render-worker/`) | The unit suite, the render worker and the container jobs |
| The store (`store/`, `db/`, `tests/store/`, `alembic.ini`) | Plus `make test-store` and the PostgreSQL legs of the launch check, container e2e and Immich gate |
| The image or its deployment (`docker/`, `docker-compose.yml`, `deploy/`, `services/`, `packages/`) | Plus the Docker builds and container e2e, the unit suite on one cell |
| `pyproject.toml`, `uv.lock`, `Makefile`, a workflow, `tests/conftest.py`, or a path no rule knows | Everything |

**Main and releases run everything.** `ci.yml` and `immich-gate.yml` run on every push to `main`,
and the release calls both through `workflow_call`, a nightly included. The scope only ever narrows
a `pull_request`: for any other event `ci_scope.py` answers "everything", whatever the diff, and
`tests/test_ci_scope.py` holds it to that. Outside pull requests each run gets a concurrency group
of its own, so one merge never cancels the previous merge's run.

`make ci-scope` prints what the current branch would run. Branch protection requires `CI Success`
and `Immich Gate`, the two rollups. A job the scope skipped counts as passing there; a failed,
timed-out or cancelled one does not, and `Immich Gate` fails when the scope said the gate should
run and it didn't. So skipping a job or adding a matrix leg never leaves a required check unreported.

`make ci` runs the same gates locally plus the unit tests; the Makefile is the list. CI adds what
needs a remote or a diff: commitlint, pip-audit, gitleaks, hadolint.

## The pre-commit hook

The hook runs the gates and tests a commit can affect, not all of them. On a one-file source change
that is about 2 to 3 minutes instead of 5 on an idle machine, and a fraction of the CPU, which is
what counts when several worktrees commit at once.

**Gates run when a staged file is one of their inputs** (`files:` in `.pre-commit-config.yaml`):

| Staged | Gates |
|---|---|
| Anything | Gitleaks, the private-terms gate, the unit tests the change can affect |
| `src/` or `services/` Python, `pyproject.toml`, `uv.lock`, `Makefile` | mypy, file length, refurb, Xenon, Vulture, Bandit, complexipy, deptry, import-linter, jscpd |
| Python in `src/`, `services/` or `tests/` | `make critique` |
| `src/immich_memories/` Python | The CLI and config reference checks, which are generated from source |
| `docs-site/` | The docs build; `docs-site/docs/` and `README.md` add the voice gate, the documented-commands check and the feature inventory |
| `.github/workflows/` | `make workflow-guard` |
| `web/`, `src/immich_memories/web/` | `make web-check` |
| The diagrams, `docker-compose.yml`, `uv.lock`, research data | Their own check |

**Tests come from a map of what each test file ran.** `scripts/hook_scope.py` (`make hook-tests`)
reads the coverage of the last green full run, recorded per test with `--cov-context=test`, and
picks:

- for a change inside function bodies, the test files that executed the module;
- for a change that runs on import (a signature, a constant, a decorator, a new function), also the
  modules that read its names while they are imported, and every test that executed or imports one
  of them; a name it no longer defines adds every test that imports, at any depth, a module whose
  load imports that name;
- for a doc page, a workflow, a script or package data, the files that name it, and what imports them;
- the tests that walk the repository, on every commit, and the tests that start the app in a child
  process (the map can't see into it), on every source change;
- a changed test file, and the tests below a changed `conftest.py`.

Before running the subset, the hook imports each changed source module in a fresh interpreter and
collects the whole suite (about 10 seconds), which imports every test module, so a module that no
longer loads, a circular import or a broken decorator still fails the commit. diff-cover
then checks 80% of the changed lines, as before.

The whole suite runs when the selection can't vouch for itself: no map yet (the first commit on a
machine), `tests/conftest.py`, `tests/immich_fakes.py`, `tests/e2e/fake_*.py`, `pyproject.toml`,
`uv.lock`, `Makefile` or the hook config changed, a change to what the package or the root conftest
loads on start (config, the Immich models), source data nothing names, a source module no test
reaches, more than half the suite selected, or git failing to say what changed. A full run records
a new map in the git directory every worktree shares; everything that changed since the mapped
tree counts as changed, so an old map or one from another branch only selects more.

To run everything: `HOOK_FULL=1 git commit`, `make pre-commit` (every hook, every file, the whole
suite) or `make ci`. Main, the release and the nightly run every suite in CI either way, so a
selection miss surfaces within the hour of a merge, before any release.

## Quality gates

| Gate | Tool | What it catches |
|---|---|---|
| Lint + format | Ruff | Style, import ordering, unused imports |
| Type check | mypy | Type mismatches, missing annotations |
| Complexity | Xenon + complexipy | Xenon grade C max, cognitive complexity ≤15 |
| File length | Makefile script | Over 800 lines warns, over 1000 fails |
| Dead code | Vulture | Unused functions, variables, imports |
| Duplication | jscpd | Copy-pasted blocks (≤5%) |
| Modernization | refurb | Idioms a newer Python replaced |
| AI smells | `make critique` | Over-structured code, docstrings that restate the signature |
| Security | Bandit + Semgrep | Common vulnerability patterns |
| Secrets | Gitleaks | Committed API keys |
| Dependencies | pip-audit + deptry | Known CVEs; unused, missing or transitive imports |
| Architecture | import-linter | The core packages (`analysis`, `processing`, `titles`, `people`, `store`, `triage`, `operations`, `free_text`) must not import `cli`, and neither may `audio`. They plus `cache` and `tracking` must not import the web server (`web`). `web` runs the CLI as a child process and never imports it. The inference service in `services/inference` imports neither, and the app never imports it |
| Compose | `make compose-check` | A `docker-compose.yml` that only parses with the repo beside it |
| Commits | commitizen | Non-conventional commit messages |
| Docs | docs-voice, docs-cli-check, docs-config-check, notices-check | Chatbot prose and em dashes; drift between the generated references and the code |
| Tests | pytest | The unit suite in CI; integration and e2e locally and on the GPU runner |

`docs-voice` and `notices-check` run in `make ci`, the pre-commit hooks and the CI quality job.
For optional packages absent from that environment, notices reuse the recorded licence and URL
only for the exact package name and version. A new version without installed metadata or a
reviewed fallback fails for review. That is cached provenance, not a fresh licence audit.
