---
title: CI and quality gates
---

# CI and quality gates

## CI pipeline

CI runs in tiers, cheap to expensive, and a pull request only runs the jobs its changes can break.

- **Tier 0: change scope and cache setup.** `make ci-scope` (`scripts/ci_scope.py`) sorts the diff
  into areas and every later job reads the answer in its `if:`. Every job that installs the project
  waits on the cache setup.
- **Tier 1: quality gates** (the table below), one job, steps in order, each carrying
  `if: !cancelled()` so the first failure doesn't hide the rest. Commitlint runs on pull requests
  only. A second job runs the security scans in parallel.
- **Tier 2: tests**, after both tier 1 jobs pass. The unit suite (Ubuntu on 3.11/3.12/3.13; macOS on
  3.13 for a pull request, all three for a release workflow call), plus `make test-extras`. Neither extras job pulls
  torch, so what runs there is the subset that survives without it; the rest is a local target.
- **Tier 3: build**, after tests. Package build, and the Docker image on pull requests.

The docs build starts immediately. The hermetic launch check runs on pull requests off the cache
setup alone, Playwright e2e against a fake Immich: `make launch-check-ci` on SQLite, and
`make launch-check-ci-postgres` too when the store changed. After the tests, the container e2e job
builds the image and runs `make test-container` on each backend.

What a pull request runs:

| The diff touches | Runs |
|---|---|
| Only docs (`docs-site/`, `docs/`, `*.md`) | Quality, security, the unit suite on one cell, the docs build if `docs-site/` changed |
| Code (`src/`, `tests/`, `scripts/`) | The above plus the full test matrix, extras, package build, launch check and Immich gate on SQLite |
| The store (`store/`, `db/`, `tests/store/`, `alembic.ini`) | Plus `make test-store` and the PostgreSQL legs of the launch check, container e2e and Immich gate |
| The image or its deployment (`docker/`, `docker-compose.yml`, `deploy/`, `services/`, `packages/`) | Plus the Docker builds and container e2e |
| `pyproject.toml`, `uv.lock`, `Makefile`, a workflow, `tests/conftest.py`, or a path no rule knows | Everything |

CI runs on pull requests and `workflow_call`, not pushes to `main`.
The release calls CI through `workflow_call` and always runs everything. `make ci-scope` prints
what the current branch would run. Branch protection requires `CI Success` and `Immich Gate`, the
two rollups, so skipping a job or adding a matrix leg never leaves a required check unreported.

`make ci` runs the same gates locally plus the unit tests; the Makefile is the list. CI adds what
needs a remote or a diff: commitlint, pip-audit, gitleaks, hadolint.

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
