# GitHub Actions Workflows

These workflow files and templates need to be manually added to your repository.

## Quick Setup

```bash
# Create directories
mkdir -p .github/workflows
mkdir -p .github

# Copy workflows
cp docs/github-workflows/ci.yml .github/workflows/
cp docs/github-workflows/release.yml .github/workflows/
cp docs/github-workflows/pr-automation.yml .github/workflows/

# Copy templates
cp docs/github-templates/labeler.yml .github/
cp docs/github-templates/pull_request_template.md .github/

# Commit and push (requires write access to workflows)
git add .github/
git commit -m "ci: Add GitHub Actions workflows and templates"
git push
```

## Workflow Descriptions

### `ci.yml` - Continuous Integration

Runs on pull requests, on every push to `main`, and when the release (a nightly included) calls it. All jobs use `make` targets as the single source of truth for commands.

A pull request runs only the jobs its changes can break: the `changes` job runs `make ci-scope` (`scripts/ci_scope.py`), which answers one output per heavy job, and every other job reads its output in its `if:`. Build and dependency files, workflows and unknown paths run everything. A push to `main` and a release are never scoped: every job runs, in a concurrency group of its own so no merge cancels another's run. The table of what runs when is in `docs-site/docs/contribute/ci.md`. The render worker's suite is a job here too (it used to be `render-worker.yml`).

`CI Success` rolls every job up and is the check branch protection requires; a job the scope skipped counts as passing there, a failed, timed-out or cancelled one does not.

Run the full CI pipeline locally with `make ci`, and `make ci-scope` to see what your branch would run.

### `immich-gate.yml` - Real-Immich Gate

Runs on pull requests, on every push to `main`, and when the release calls it. The gate on Immich v2, 3.2 and v3 and the feature tests on a real Immich run when the scope's `immich` output says the app, the fakes, the seeding or these suites changed; on `main` and in a release, always. `Immich Gate` is the required rollup: it passes a skipped gate only when the scope said nothing it reads changed.

### `release.yml` - Release

Runs when dispatched (`stable` or `rc`) and when `nightly.yml` calls it (`nightly`).

**How it works:**
1. Analyzes commits AND merged branch names since last release
2. Determines version bump based on:

   **Branch names (checked first):**
   - `breaking/*` or `major/*` → Major version bump (0.1.0 → 1.0.0)
   - `feat/*`, `feature/*`, or `minor/*` → Minor version bump (0.1.0 → 0.2.0)
   - `fix/*`, `bugfix/*`, `patch/*`, or `hotfix/*` → Patch version bump (0.1.0 → 0.1.1)

   **Commit types (conventional commits):**
   - `feat!:` or `BREAKING CHANGE:` → Major version bump
   - `feat:` → Minor version bump
   - `fix:`, `perf:` → Patch version bump

3. Creates git tag and GitHub Release
4. Builds and pushes Docker images

> **Note:** Releases publish to GitHub Releases, GHCR (multi-arch Docker image) and [PyPI](https://pypi.org/project/immich-memories/) via OIDC trusted publishing.

**Environments required:**
- `production` - For minor/patch releases
- `production-major` - For major releases (add approval requirement)

### `nightly.yml` - Nightly Build

Runs daily and on demand (`force` builds an unchanged `main`). It builds only when `main` has commits since the last nightly, read from the `Commit:` line of the rolling `nightly` prerelease (`scripts/nightly.py`). That check is all `nightly.yml` holds: the build is `release.yml` called with channel `nightly`, the same jobs in the same order as a stable or rc release. Where a nightly differs, it is an `if:` in `release.yml`: it runs CI and the Immich gate in full like every release, but skips the approval environment, rebuilds the inference images only when their inputs changed, tags `:nightly` and `:nightly-YYYYMMDD` instead of a version, moves the `nightly` tag instead of a `v*` tag, replaces the rolling `nightly` prerelease (wheel, sdist, provenance and Compose files, never "Latest") instead of creating a versioned release, and skips PyPI. The docs deploy lands it at `/dev/`. A **Release** dispatch offers only `stable` and `rc`; a nightly runs through **Nightly**, so it always passes the check.

### `docs.yml` - Deploy Docs

Called by the release and the nightly, or run by hand. Every deploy rebuilds all docs tracks, each from its own ref (`scripts/docs_release.py`): stable at the root, the newest newer release candidate at `/next/`, the latest nightly's commit at `/dev/`.

### `image-maintenance.yml` - Image Maintenance

Weekly: inventories and audits the packages in the built images. Daily: deletes image versions whose only tags are `nightly-YYYYMMDD` dates older than 14 days (`scripts/prune_nightly_images.py`).

### `pr-automation.yml` - PR Automation

Runs on pull request events.

**Features:**
- Auto-labels PRs based on files changed
- Validates PR title follows conventional commits
- Adds size labels (XS, S, M, L, XL)
- Flags breaking changes for maintainer review
- Welcomes first-time contributors

## GitHub Repository Setup

### 1. Create Environments

Go to Settings → Environments and create:

| Environment | Description | Protection Rules |
|-------------|-------------|------------------|
| `production` | Minor/patch releases | Optional: require approval |
| `production-major` | Major releases | **Required: require approval from maintainers** |

### 2. Configure Branch Protection

Go to Settings → Branches → Add rule for `main`:

- [x] Require a pull request before merging
- [x] Require approvals (1+)
- [x] Require status checks to pass
  - `CI Success`
  - `Immich Gate`
  - `Validate PR Title`
- [x] Require conversation resolution before merging
- [x] Require signed commits (optional but recommended)
- [x] Do not allow bypassing the above settings

### 3. Configure Labels

Create these labels in your repository (Settings → Labels):

**Type labels:**
- `breaking-change` (red)
- `needs-maintainer-review` (orange)
- `documentation` (blue)
- `tests` (green)
- `ci` (purple)
- `dependencies` (yellow)

**Size labels:**
- `size/XS`, `size/S`, `size/M`, `size/L`, `size/XL`

**Area labels:**
- `area/api`, `area/analysis`, `area/processing`, `area/ui`, `area/cli`

**Platform labels:**
- `platform/mac`, `platform/nvidia`

## Semantic Versioning

Version bumps are automatic based on **branch names** and **commit messages**.

### Branch Naming Conventions

Use descriptive branch names to automatically determine the release type:

| Branch Pattern | Examples | Version Bump |
|----------------|----------|--------------|
| `breaking/*`, `major/*` | `breaking/new-config-format` | Major (0.1.0 → 1.0.0) |
| `feat/*`, `feature/*`, `minor/*` | `feat/music-overlay` | Minor (0.1.0 → 0.2.0) |
| `fix/*`, `bugfix/*`, `patch/*`, `hotfix/*` | `fix/memory-leak` | Patch (0.1.0 → 0.1.1) |

### Commit Message Conventions

Commits are also analyzed using [Conventional Commits](https://www.conventionalcommits.org/):

| Commit Type | Example | Version Bump |
|-------------|---------|--------------|
| `fix:` | `fix: resolve memory leak` | Patch (0.1.0 → 0.1.1) |
| `perf:` | `perf: optimize video encoding` | Patch |
| `feat:` | `feat: add music overlay` | Minor (0.1.0 → 0.2.0) |
| `feat!:` | `feat!: change API response format` | Major (0.1.0 → 1.0.0) |
| `BREAKING CHANGE:` in body | Any commit with breaking change | Major |

> **Priority:** Branch names are checked first, then commit messages. The highest severity wins (major > minor > patch).

### Pre-release Versions

Pre-release versions are generated on non-main branches:
- `dev/*`, `feature/*` branches → `0.2.0.dev1`
- `rc/*` branches → `0.2.0rc1`

## Commit Message Format

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`

**Examples:**
```
feat(ui): add dark mode toggle
fix(api): handle pagination correctly for large libraries
docs: update installation instructions
feat!: redesign configuration format

BREAKING CHANGE: Configuration file format has changed.
See migration guide in docs/migration.md
```
