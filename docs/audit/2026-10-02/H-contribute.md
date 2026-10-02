# H: Contribute pages, root public files, sidebar and redirects

Auditor H. Repo at b371427b (branch claude/trusting-bell-6i5qev, shallow clone of 50 commits). Read only, nothing committed.
Sources of truth checked: Makefile (`make help` run, targets read), `.github/workflows/*.yml`, `scripts/ci_scope.py`, `scripts/release_analyze.py`, `pyproject.toml`, `uv.lock` (`uv sync --dry-run --offline`), `.pre-commit-config.yaml`, src/ and tests/ trees, and the GitHub REST API (release assets, rulesets, discussions, private vulnerability reporting).
Not executed: pytest (dev extra not installed in `.venv`), Docker targets, docs build.

## 1. Coverage

| Page / file | Claims checked (approx.) | Findings | Verdict |
|---|---|---|---|
| contribute/development-setup.md | 45 | 7 | Mostly right. Wrong about `make help`; `make check`/`make dev` on Linux install the two onnxruntime builds together; empty legacy anchors at the end |
| contribute/architecture.md | 40 (every class, function and path named) | 3 | Every symbol exists. The memory-type recipe is wrong about the web select; "constructor injection" is loose |
| contribute/testing.md | 60 | 8 | Detailed and mostly right. `test-fast`, `make help`, clip length, "no model", CI Docker, PostgreSQL legs and the encoder claim are off |
| contribute/ci.md | 45 | 5 | Close to the workflows. The pre-commit claim, "all three on main" and the omitted gates are wrong |
| contribute/releasing.md | 35 | 2 | Matches release.yml and release_analyze.py. Small gaps only |
| contribute/demo-assets.md | 40 | 0 | Verified: counts, paths, frame counts, symlinks, recipes |
| contribute/code-of-conduct.md | 4 | 0 | OK (v2.1, private reporting is enabled) |
| CONTRIBUTING.md | 45 | 7 | Contradicts development-setup on the first command. Overclaims enforcement; stale anchor link; `make help` |
| DISCLAIMER.md | 20 | 3 | "800-line limits" is untrue as a gate, and integration does not block merges |
| SECURITY.md | 25 | 5 | Scorecard trigger and pip-audit scope are wrong; the verify example uses a release without attestations; RC filenames break it |
| CODE_OF_CONDUCT.md | 5 | 0 | OK |
| deploy/kubernetes/README.md | 40 | 4 | Store files stale (backup advice points at a legacy file); "six heads"; overlays missing from the tree; em dashes |
| examples/config.example.yaml (header + inline comments) | 10 | 2 | Loads fine through `Config.from_yaml`; two stale comments |
| Root links from docs/README | 13 blob/tree links + all relative links in root .md | 0 missing | All targets exist |
| ARCHITECTURE.md (symbol and path existence sweep) | 562 file tokens, every backticked class and function | 0 | Every named class, function and file exists (some by suffix shorthand) |
| sidebars.ts | 102 docs | 1 | Three docs in no sidebar |
| redirects.ts | 43 redirects | 0 | Every target exists; no `from` path collides with a live page |
| CLAUDE.md (cross-page only) | 6 | 3 | Contradicts the Makefile, pyproject and testing.md |

Totals: BLOCKER 0, WRONG 22, GAP 9, CLARITY 9, POLISH 4 (44 findings).

## 2. Findings

### H-1 [WRONG] contribute/development-setup.md:52; testing.md:7, 21-22; CONTRIBUTING.md:37: `make help` does not list every target
- **Claim:** "`make help` lists every target"; "`make help` lists every per-suite target with its runtime"; "Run `make help` to see everything".
- **Reality:** `help` is a hand-written echo block (Makefile:8-72) with 47 entries. The Makefile has about 200 targets. It lists none of `test-integration*`, `test-store*`, `test-extras`, `test-immich-gate`, `test-container`, `launch-check-ci`, `dev-test`, `install-acestep`, `web-*`, `ui-catalogues` or `demo-*`. Its own `ci` line ("check + dead-code + security-lint") is also stale.
- **Evidence:** `make help | grep -cE '^  [a-z]'` prints 47. `make help | grep -E 'integration|store|extras|gate|container|web-|dev-test'` matches only `test-fast` and `privacy-gate`.
- **Fix:** Generate `help` from the `## ` comments, which many targets already carry (`grep -E '^[a-zA-Z_-]+:.*?## '`). Or change the docs to "read the Makefile".
- **Confidence:** VERIFIED

### H-2 [WRONG] contribute/testing.md:20: `make test-fast` runs more than `make test`, not less
- **Claim:** "`make test-fast` skips tests marked slow; the full suite is `make test`."
- **Reality:** `test-fast` is `pytest -v -m "not slow"` (Makefile:482). A command-line `-m` replaces the `-m 'not integration and not e2e and not container'` in addopts (pyproject.toml:675). The Makefile says so itself at the test-extras comment: "A CLI -m replaces addopts, so the integration and e2e exclusions are restated". So `test-fast` also collects the integration, e2e and container tests that `make test` deselects.
- **Fix:** Use `-m "not slow and not integration and not e2e and not container"`, or drop the target.
- **Confidence:** LIKELY. pytest was not run (dev extra not installed). The reasoning rests on pytest's last-`-m`-wins rule and the Makefile's own comment.

### H-3 [WRONG] contribute/architecture.md:75: the web Memory page does not read `OFFERED_MEMORY_TYPES`
- **Claim:** "Add it to `OFFERED_MEMORY_TYPES` … `--memory-type` and the Memory page's select both read that tuple, in that order".
- **Reality:** Only the CLI reads it (`cli/generate_options.py:147`). The web select iterates `TYPES = Object.keys(FIELDS)`, a hard-coded map in `web/src/routes/create/+page.svelte:18-39`. That map is in a different order (`monthly_highlights` first) and has an extra `custom` entry. Labels come from `web/src/lib/labels.ts`. No `/api/v1` endpoint exposes the tuple (grep of `src/immich_memories/web/*.py` finds nothing). The comment at `memory_types/registry.py:25` repeats the same stale claim.
- **Fix:** Add steps: "add the type and its fields to `FIELDS` in `web/src/routes/create/+page.svelte`, and a label in `web/src/lib/labels.ts`, then run `make ui-catalogues`". Or make the client fetch the list.
- **Confidence:** VERIFIED

### H-4 [WRONG] contribute/testing.md:13: integration clips must be 15 s or shorter, not under 30 s
- **Claim:** "at least two clips under 30s in that library".
- **Reality:** `find_short_clips` uses `MAX_CLIP_DURATION = 15` (tests/integration/immich_fixtures.py:76). The skip message says "≤60s" (tests/integration/pipeline/conftest.py:33), which is a third number.
- **Fix:** Say "15 s or shorter", and fix the skip message.
- **Confidence:** VERIFIED

### H-5 [WRONG] contribute/testing.md:39-40: the gate runs local models and fetches them
- **Claim:** "a rules-tier config (no model, no network beyond this Immich)".
- **Reality:** The config is `tier: nas` with a DINOv2 ONNX encoder, the Marqo NSFW ONNX model and a detector cache (tests/integration/immich_gate/seed.py:207-231). `immich-gate-run` runs `immich-memories models fetch` before the tests (Makefile:403-404), and CI caches `.immich-gate/models` (immich-gate.yml "Cache NAS model artifacts"). A cold run downloads the pinned artifacts.
- **Fix:** "the NAS tier with its local ONNX models and no LLM or caption provider; the first run downloads the pinned model artifacts".
- **Confidence:** VERIFIED

### H-6 [WRONG] contribute/testing.md:73: CI does not build the Docker image on every PR
- **Claim:** "CI builds the Docker image on every PR".
- **Reality:** The `docker` and `container-e2e` jobs run only when `needs.changes.outputs.container == 'true'`, and container-e2e also when `store == 'true'` (ci.yml:493, 533-536). `container` is true only for docker/, deploy/, services/, packages/, tests/container/ or an "everything" path (scripts/ci_scope.py CONTAINER and EVERY_JOB). ci.md:34 states the scoping correctly, so the two pages contradict each other.
- **Fix:** "CI builds the image on PRs that touch the image, its deployment or the store".
- **Confidence:** VERIFIED

### H-7 [WRONG] contribute/testing.md:29-30, 55; CONTRIBUTING.md:53, 69: the gate does not run on every PR, or twice per major
- **Claim:** "The Immich Gate check does [this], on every PR, for both majors"; "Every test runs twice per major: the app's store on SQLite, and on PostgreSQL"; "Every PR runs it for both versions".
- **Reality:** On a docs-only PR the gate job is skipped and the rollup passes (immich-gate.yml:56 `docs_only != 'true'`; the `gate` job exits 0 for docs-only). The PostgreSQL legs run only when the store changed (`database: … store == 'true' && ["sqlite","postgresql"] || ["sqlite"]`). A push to main runs both. ci.md:32-33 states this correctly, so the pages contradict each other.
- **Fix:** "on every PR that touches code; on PostgreSQL too when the store changes, and always on main".
- **Confidence:** VERIFIED

### H-8 [WRONG] contribute/testing.md:164-168: photo encoder selection has moved
- **Claim:** "`render_single_photo` picks its encoder from `check_zscale_available()`: with zscale it uses `hevc_videotoolbox`, without it `libx264`."
- **Reality:** zscale now picks the transfer only (`photos/photo_pipeline.py:225-234`, PQ or NONE). The encoder comes from `photo_encoding_plan` → `resolve_encoding_plan` with `detect_hardware_acceleration` (photos/encoding.py:24-54; processing/encoding_plan.py:292-330). Without zscale the plan is H.264, but on a Mac with hardware enabled `get_ffmpeg_encoder` can still choose `h264_videotoolbox`. So stubbing only `check_zscale_available` may not force software.
- **Fix:** Re-derive the advice. The likely fix is to also stub hardware detection, or pass a config with `hardware.enabled=False`.
- **Confidence:** LIKELY. Not run on macOS CI.

### H-9 [WRONG] contribute/ci.md:65: docs-voice and notices-check are not pre-commit hooks
- **Claim:** "`docs-voice` and `notices-check` run in `make ci` and the pre-commit hooks, not in the CI job."
- **Reality:** `.pre-commit-config.yaml` has no hook for either (its hooks are ruff, ruff-format, gitleaks, private-terms ×2, commitizen, mypy, file-length, refurb, complexity, dead-code, security-lint, cognitive-complexity, dep-check, arch-check, duplication, diff-cover-check). `docs-brand` and `docs-commands` are also in `make ci` (Makefile:809) and in no workflow (grep of .github/workflows finds none). The page does not mention them.
- **Fix:** "run only in `make ci`: docs-voice, notices-check, docs-brand and docs-commands are not checked on PRs". Better: add them to the Quality Gates job, since the merge train merges on CI alone (see H-28).
- **Confidence:** VERIFIED

### H-10 [WRONG] contribute/ci.md:17-18: "all three on `main`" is not true
- **Claim:** "macOS on 3.13 for a pull request, all three on `main`".
- **Reality:** ci.yml triggers only on `pull_request` and `workflow_call`. The full six-cell matrix runs only when release.yml calls it. A push to main runs main-push.yml instead: one ubuntu/3.12 cell, `make test` and `make typecheck`. main-push.yml is not mentioned anywhere on the page.
- **Fix:** "all three on a release run". Add a line on main-push.yml (unit suite and type check on the merged result, not required) and on mirror.yml/integration.yml (the GPU integration suite after merge, see H-29).
- **Confidence:** VERIFIED

### H-11 [GAP] contribute/ci.md:29-35: the scope table omits paths
- **Reality (scripts/ci_scope.py):** Docs also include `.github/ISSUE_TEMPLATE/*`. Code also includes `examples/*`, `complexity-watermark.json`, `vulture-whitelist.py` and `THIRD_PARTY_NOTICES*`. Store also includes `scripts/with_throwaway_postgres.sh`. Container also includes `.dockerignore` and `tests/container/`. "Everything" also includes `.python-version`, `.github/actions/*` and `scripts/ci_scope.py`. A `*.md` under src/ or deploy/ counts as code, not docs.
- **Fix:** Add these, or say "abridged; `scripts/ci_scope.py` is the list".
- **Confidence:** VERIFIED

### H-12 [WRONG] CONTRIBUTING.md:6 (and 43): `make ci` does not run "the same gates CI runs"
- **Reality:** CI also runs commitlint, pip-audit, gitleaks, hadolint, diff-cover, the extras/store/launch/container jobs and the Immich gate. `make ci` runs gates that CI does not (docs-voice, notices-check, docs-brand, docs-commands). ci.md:41-42 describes this accurately.
- **Fix:** Reuse ci.md's sentence.
- **Confidence:** VERIFIED

### H-13 [CLARITY] CONTRIBUTING.md:6, 33 vs development-setup.md:15-28: two different first commands
- **Claim:** CONTRIBUTING says `make dev` "installs everything" and is the setup. development-setup says `make dev-test` is the "Default for contributors". CLAUDE.md:15 says "Install dev dependencies first: `make dev`".
- **Why it matters:** A first-time contributor reading both cannot tell which to run. `make dev` needs Node and on Linux pulls torch plus about 15 nvidia CUDA wheels (`uv sync --all-extras --dry-run --offline | grep -ci nvidia` prints 15).
- **Fix:** Pick one recommendation and use it on all three pages.

### H-14 [WRONG] development-setup.md:28, 49-50; CONTRIBUTING.md:33: on Linux, `make dev`, `make check` and `make ci` install both onnxruntime builds
- **Claim:** `make dev` installs "every declared extra (torch, demucs, editorial)". `ensure-dev` "turns a `make dev-test` environment into a `make dev` one".
- **Reality:** `--all-extras` also installs `editorial-cuda`. pyproject.toml:123-127 says that extra "REPLACES `editorial`, never joins it… installing both distributions puts two copies of the same import name in one environment". No `[tool.uv] conflicts` is declared.
- **Evidence:** `uv sync --all-extras --inexact --dry-run --offline | grep -i onnx` prints `+ onnxruntime==1.28.0` and `+ onnxruntime-gpu==1.26.0`.
- **Second issue:** `ensure-dev` does not build the web client, so the result is not "a `make dev` one" until `web-check` (in `make ci` only) builds it.
- **Fix:** Use `--extra all --extra dev` in `dev`/`ensure-dev`, or declare `conflicts` in `[tool.uv]`. Then correct the table.
- **Confidence:** VERIFIED (resolution only; import behaviour not executed)

### H-15 [GAP] development-setup.md:45-50: "Check the install" downloads gigabytes without warning
- **Claim:** "If it passes, your setup is correct."
- **Reality:** The page sends a `make dev-test` user (no torch, no CUDA) to `make check`. Its `ensure-dev` installs torch and the nvidia wheels (about 115 packages per the dry run). This is the very install the previous paragraph said `dev-test` avoids.
- **Fix:** Say what it downloads. Offer `make lint typecheck test` as the light check for `dev-test` users.
- **Confidence:** VERIFIED (dry-run counts)

### H-16 [WRONG] CONTRIBUTING.md:135: the "merging and releasing" link lands on an empty anchor
- **Claim:** "See [merging and releasing](docs-site/docs/contribute/development-setup.md#merging-and-releasing)."
- **Reality:** That anchor is an empty `<span id>` at the end of development-setup.md (lines 134-137), kept from before the content moved to releasing.md. The reader lands at the bottom of the page with nothing there. architecture.md:94-95 has the same kind of leftover spans (`ci-pipeline`, `quality-gates`).
- **Fix:** Link `docs-site/docs/contribute/releasing.md#merging-and-releasing`. Keep the spans only if external links need them, and make them redirect visibly.
- **Confidence:** VERIFIED

### H-17 [WRONG] CONTRIBUTING.md:82: these rules are not "enforced by CI and pre-commit hooks"
- **Claim:** "These are enforced by CI and pre-commit hooks. Not suggestions."
- **Reality:** TDD, "test behaviour through public APIs", "no testing arithmetic", "split along cohesion" and "no docstrings that restate the signature" have no automated check. "Every mock gets a `# WHY:` comment" is a ratchet: `MAX_PATCHES_WITHOUT_WHY = 651` (scripts/critique_tests.py:32) tolerates 651 unexplained patches. "Integration tests exist for FFmpeg pipeline changes" has no gate either.
- **Fix:** Split the list into "enforced" and "expected in review".
- **Confidence:** VERIFIED

### H-18 [WRONG] DISCLAIMER.md:23; CLAUDE.md "Max file length: 800 lines": there is no 800-line limit
- **Claim:** "800-line file length limits" in the list a sceptical reader is told to check.
- **Reality:** `file-length` warns above 800 and fails only above 1000 (Makefile:526-547). Four files are over 800 today: `cli/_pipeline_runner.py` 866, `analysis/special_day.py` 826, `analysis/editorial_story_shortlist.py` 820, plus one at 796. CONTRIBUTING.md:86 and ci.md:51 state 800/1000 correctly. CLAUDE.md ("≤800 lines per .py file"), the CI step name "File Length (≤800 lines)" and `make help` all repeat the 800 figure.
- **Fix:** "800-line soft limit, 1000-line hard limit" everywhere.
- **Confidence:** VERIFIED

### H-19 [CLARITY] DISCLAIMER.md:19, 36: the integration suite does not block merges
- **Claim:** The list includes "an integration suite", followed by "The build stays red until they pass."
- **Reality:** On PRs only the FFmpeg-only suites the diff touches run (for diff-cover). The full integration suite runs on the private GPU mirror after a push to main (mirror.yml triggers `push: main` and `workflow_dispatch`). It cannot keep a PR red. The cognitive-complexity gate also grandfathers 13 files over 15 (complexity-watermark.json).
- **Fix:** "runs after merge on a self-hosted GPU runner". Mention the complexity watermark.
- **Confidence:** VERIFIED

### H-20 [WRONG] SECURITY.md:48-49: Scorecard does not run on pushes to main
- **Claim:** "OpenSSF Scorecard runs on its own schedule and on pushes to `main`."
- **Reality:** scorecard.yml triggers on `branch_protection_rule`, a nightly `schedule` and `workflow_dispatch`. Its comment says "Nightly, not on every push to main".
- **Confidence:** VERIFIED

### H-21 [WRONG] SECURITY.md:99: pip-audit does not block "any" vulnerable dependency
- **Claim:** "The pip-audit gate blocks any PR that introduces a dependency with a known CVE."
- **Reality:** `pip-audit` audits `uv export --frozen --extra dev` (Makefile:676). That is the base and dev dependencies only. The `editorial`, `demucs` (torch), `auth`, `audio` and `music` extras are not audited, yet the image ships `INSTALL_EXTRAS=all`. Also, `pip_audit_smart.py` "warns on unfixable vulns, fails on fixable ones", so a CVE with no fixed release passes. That is exactly the NLTK case the same page describes.
- **Fix:** Audit `--all-extras` (or `--extra all`), and say "blocks fixable CVEs".
- **Confidence:** VERIFIED

### H-22 [WRONG] SECURITY.md:80-85: the verify example uses a release without attestations
- **Claim:** `VERSION=0.59.2` followed by `gh attestation verify … --bundle "immich_memories-$VERSION.sigstore.json"`.
- **Reality:** The v0.59.2 release assets are the wheel and the tar.gz only (`gh api repos/…/releases/tags/v0.59.2 -q '.assets[].name'`). The command fails because the bundle does not exist. v0.103.0 does carry `.sigstore.json` and `.intoto.jsonl`.
- **Fix:** Use a recent version (0.103.0 or newer) in the example.
- **Confidence:** VERIFIED

### H-23 [GAP] SECURITY.md:80-84: the verify commands break for release candidates
- **Reality:** release.yml names the bundle `immich_memories-${NEXT_VERSION}.sigstore.json`, where NEXT_VERSION is `1.0.0-rc.1`, and tags `v1.0.0-rc.1`. The wheel is PEP 440-normalized to `immich_memories-1.0.0rc1-py3-none-any.whl` (releasing.md:60 says the PyPI version is `1.0.0rc1`). A tester who sets `VERSION=1.0.0-rc.1` gets the wrong wheel filename.
- **Fix:** Show both spellings for an RC, or name the bundle with the normalized version.
- **Confidence:** LIKELY. Wheel normalization was not built; inferred from hatch-vcs/setuptools_scm behaviour and releasing.md:60. Distinct from the known "image provenance" gap.

### H-24 [WRONG] deploy/kubernetes/README.md:68, 228-230: the store files listed are stale, so the backup advice is wrong
- **Claim:** The cache PVC holds "`cache/annotations.sqlite` (every banked fact and reading), `cache.db` (run history, automation state)". "`cache/annotations.sqlite` on the cache PVC is the expensive part… Back up the PVC."
- **Reality:** The store is `sqlite:///~/.immich-memories/store.db` (config_models.py:135; `make info` says the same). `annotations.sqlite` is "the legacy annotations.sqlite the store imports from; nothing else reads it" (config_models_editorial.py:232). Line 233 of the same README says `store backup` covers "decisions, model answers, run history". "Back up the PVC" still saves the user, but the named file is the wrong one. The example config's `cache:` comment ("the annotation store") is stale in the same way.
- **Fix:** Name `store.db` and point to `immich-memories store backup`.
- **Confidence:** VERIFIED (code); not run in a pod

### H-25 [WRONG] deploy/kubernetes/README.md:128: the inference service has eight heads
- **Claim:** "the encoder, the six heads and the two detectors".
- **Reality:** The bundled heads are `public-8heads-v4.npz` (src/immich_memories/triage/bundled_heads). ARCHITECTURE.md:350, reference/inference-service.md:7 and development-setup.md:98 all say eight.
- **Confidence:** VERIFIED

### H-26 [GAP] deploy/kubernetes/README.md:13-24: two overlays are missing from the tree
- **Reality:** `overlays/maximalist/` and `overlays/render-sidecar/` exist (find deploy/kubernetes) but appear neither in the tree nor in any section.
- **Fix:** List them with one line each, or remove them.
- **Confidence:** VERIFIED

### H-27 [POLISH] deploy/kubernetes/README.md:10, 55, 102, 198; examples/config.example.yaml:1; ARCHITECTURE.md (two): em dashes
- **Evidence:** `.venv/bin/python scripts/docs_voice_gate.py … deploy/kubernetes/README.md` reports 4 em dash hits. `grep -c '—'` reports 1 in the example config and 2 in ARCHITECTURE.md. The gate only covers README.md and docs-site/docs, so these pass CI.
- **Fix:** Rewrite those sentences, or extend `DEFAULT_TARGETS`.

### H-28 [GAP] contribute/ci.md and CONTRIBUTING.md: neither says that green CI means merge
- **Reality:** DISCLAIMER.md:11 and CLAUDE.md say the merge train squash-merges green PRs. The voice, notices, brand and docs-commands gates run only in `make ci` (H-9), so a PR can merge with them red. This matters to the "built with AI" reader.
- **Fix:** Move those gates into the Quality Gates job, or say they are not merge-blocking.
- **Confidence:** VERIFIED (workflows)

### H-29 [CLARITY] CONTRIBUTING.md:52, 66; testing.md:97-98, 119: the pages do not say when the GPU runner runs
- **Reality:** The GPU runner runs after merge, on pushes to main and on manual dispatch (mirror.yml). It never runs on a PR. A contributor might wait for a GPU check that will not come.
- **Fix:** "after merge to main".

### H-30 [GAP] contribute/testing.md:111; CONTRIBUTING.md:189: `diff-cover-local` is not "same as CI"
- **Reality:** `diff-cover-local` (Makefile:686-707) does not exclude `**/analysis/apple_vision*.py` and does not apply the <10 / >1000 changed-lines skips that `diff-cover-ci` applies (Makefile:744-763). A local run can fail where CI passes.
- **Fix:** Align the targets, or note the difference.
- **Confidence:** VERIFIED

### H-31 [CLARITY] contribute/testing.md:11 vs CLAUDE.md testing-tier table: does the unit tier need FFmpeg?
- **Claim:** testing.md and CONTRIBUTING.md say the unit tier needs FFmpeg on the PATH. CLAUDE.md says "Unit … Needs: Nothing external".
- **Reality:** The unit tests do need FFmpeg (e.g. tests/test_analysis_downscale.py, tests/test_editorial_speech.py; ci.yml installs ffmpeg for the test job).
- **Fix:** Correct CLAUDE.md.
- **Confidence:** VERIFIED

### H-32 [WRONG] CLAUDE.md coverage section: the coverage floor is 65, not 55
- **Claim:** "enforced by `fail_under = 55`".
- **Reality:** pyproject.toml:684 has `fail_under = 65`. The comment above `diff-cover` at Makefile:661 says "≥95%" but the command uses `--fail-under=80`.
- **Confidence:** VERIFIED

### H-33 [CLARITY] contribute/ci.md:50: cognitive complexity "≤15" has grandfathered exceptions
- **Reality:** complexity-watermark.json lists 13 files with functions above 15, allowed under a ratchet (Makefile:622-633).
- **Fix:** "≤15 for new code; existing exceptions are ratcheted in complexity-watermark.json".

### H-34 [CLARITY] contribute/architecture.md:26: composition, not constructor injection
- **Claim:** "compose smaller service objects through constructor injection".
- **Reality:** VideoAssembler, ImmichClient and TitleScreenGenerator build their services inside `__init__` (video_assembler.py:74-87; api/immich.py:152-156; titles/generator.py:152-154). Only SmartPipeline takes an injected `planner`. Step 2 at line 61 ("Inject it into the orchestrator's `__init__`") means "construct it there".
- **Fix:** Say "compose … built in their constructors", or inject them.

### H-35 [POLISH] contribute/architecture.md:87-89: naming conventions with exceptions
- **Reality:** `generate_privacy.py` imports `titles._trip_titles`, a private module from another package (grep shows it as the only cross-package `_`-module import). `config_models_*.py` and `pinned_models.py` (a model-artifact table, not data models) break the `*_models.py` rule.
- **Fix:** Fix the import, or soften the rule.

### H-36 [GAP] sidebars.ts: three docs are in no sidebar and not marked unlisted
- **Reality:** `how-it-chooses/moments-and-stories.md` (15 lines), `how-it-chooses/picking-shots.md` (21 lines) and `how-it-chooses/what-a-model-adds.md` (13 lines) appear in no sidebar entry and carry no `unlisted:` front matter. They are linked from several pages (e.g. how-it-chooses/overrule-it.md, better/overview.md), so a reader lands on them with no sidebar context. Each shares a topic with a selection-internals page ("Picking a shot" vs "Picking each shot").
- **Fix:** Add them under "Make and improve films" beside the other how-it-chooses pages, or mark them `unlisted: true`.
- **Confidence:** VERIFIED (script comparing all 102 doc IDs against sidebar IDs; selection-internals is autogenerated)

### H-37 [CLARITY] contribute/releasing.md:44: the candidate tag is not shown anywhere visible
- **Claim:** "The workflow calculates and displays the candidate tag."
- **Reality:** release_analyze.py writes the version to `GITHUB_OUTPUT` only, not to the log or a step summary. It appears first in the release job's "Show built version" log and in a summary after publishing. The production environment approval on `docker-build` comes without the version on screen.
- **Fix:** Write a step summary in `analyze`.
- **Confidence:** LIKELY (workflow not run)

### H-38 [GAP] contribute/releasing.md: two behaviours are not documented
- (a) `auto` with only docs, chore or test commits since the last final gives `should_release=false`, and the run quietly does nothing. There is no error, unlike the candidate case.
- (b) `inference_only` skips CI and the smoke film. The `ci` job runs only for `app_only` or a real release, and `inference-build` needs only `analyze` and `release`.
- Also: a stale `make release` target (semantic-release, Makefile:979-981) plus `[tool.semantic_release]` with an `rc/*` prerelease branch (pyproject.toml) is a second, conflicting release path. The page does not mention it.
- **Confidence:** VERIFIED (code reading)

### H-39 [CLARITY] contribute/releasing.md:60: `--pre` is not the only way to install a candidate
- **Claim:** "installed only with `pip install --pre`".
- **Reality:** An exact pin (`==1.0.0rc1`) also installs it.
- **Fix:** "not picked by a default install".

### H-40 [CLARITY] development-setup.md:64-65: the app's own message points to a command that fails
- **Reality:** The page correctly says to run `make web-client` after `make dev-test`. The app's "client not built" page names `make web-build` (web/app.py:33-37), and so does hatch_build.py:22. `make web-build` is just `npm run build`, which fails without `npm ci`. The page's sentence "names the command" sends the reader to that broken advice.
- **Fix:** Make the app and hatch_build name `make web-client`.

### H-41 [GAP] contribute/testing.md:16: E2E also needs Node
- **Reality:** `e2e` depends on `web-client-present`, which builds the client with npm when it is missing (Makefile:1047-1048, 453). The table names only `make playwright-install`.
- **Fix:** Add "Node 22 (the target builds the client if absent)".

### H-42 [POLISH] CONTRIBUTING.md:121 vs development-setup.md:106: the cache module lists differ
- **Reality:** CONTRIBUTING lists "Preview, video, judgment and embedding caches". development-setup lists "Thumbnail, judgment and embedding". `cache/` has thumbnail_cache, video_cache, judgment_cache and embedding_cache, but no preview cache module.
- **Fix:** Use "Thumbnail, video, judgment and embedding" on both pages.

### H-43 [POLISH] CONTRIBUTING.md:194: the pointed-to test file opens by saying the opposite
- **Reality:** `tests/test_ffmpeg_pipe.py` begins "These tests use a real child process rather than a mock". The `Popen` patch pattern starts at line 137.
- **Fix:** Point to the test class or line.

### H-44 [CLARITY] examples/config.example.yaml:29: "nothing in the library is ever modified" is too strong
- **Reality:** With upload enabled, cleanup can move an older generated copy to Immich's trash (SECURITY.md:42-45).
- **Fix:** "with upload off, nothing in the library is modified".

## 3. Unverifiable claims (not reported as wrong)
- ci.md:38: "Branch protection requires `CI Success` and `Immich Gate`". Classic protection returns 403 to this token. The repository ruleset 13789507 (`gh api repos/…/rules/branches/main`) has deletion, non_fast_forward and pull_request (squash only, code-owner review) rules but no required_status_checks rule, so the required checks, if any, live in classic protection. Worth a look by the owner.
- DISCLAIMER.md:5, 9-11: Claude and Codex share; parallel sessions; "a check that fails twice comes back as work".
- releasing.md:71: validation against eight private households.
- development-setup.md:33: `ace_step.mode: lib` without the install renders a bundled track "and one warning".
- testing.md:36-38: EXIF camera data and the "places them" detail. Counts were verified: 133 pool (13 videos), 1,010 paging pictures, 3 people.
- demo-assets.md:52-53: the 3.8 MB hero size is from the LFS pointer (`size 3800496`); the media itself was not decoded.
- Whether pages deleted before the 50-commit shallow history lack redirects (none were deleted within it).
- CONTRIBUTING.md:216 response times; SECURITY.md:27-30 queue promises.

Verified OK (selection): every class and function in architecture.md exists (VideoAssembler and its 5 services, ImmichClient and its 5, TitleScreenGenerator and its 3, `build_smart_pipeline`, `run_editorial_source`, `plan_source`, `generate_memory` raising on no clips, the OperationalPhase order, the EditorialAttempt path and lease, db/tables files, `register_hardware_commands`, `@register_preset`). The import-linter contracts match ci.md:59. The tier jobs, `!cancelled()`, PR-only commitlint, the extras job installing neither torch nor editorial, the Immich pins v2.7.5/v3.2.2, the fetch retry of 3×180 s, the container suite steps and the curl image pin all match. The release channel logic matches: rc tag format, bump ignored while a series is open, failure with no new commit, the promotion block list, `latest` moving only on finals (app and inference), pre-release not marked Latest, docs deploy skipped for candidates, the tag pushed after the package build, the concurrency group. The private-terms resolution order and masking match. demo-assets counts (136 files, 133 pool, 18 kept, 590 km, 1,486 frames, 60 MB ceiling) and paths match. All 13 blob/tree links and all relative links in the root .md files resolve. All 43 redirect targets exist. Discussions and private vulnerability reporting are enabled.
