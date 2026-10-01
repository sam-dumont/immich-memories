---
title: Releasing
---

# Releasing

## Merging and releasing

PRs are squash-merged. Before merging a large integration branch, preserve its individual
commits on a `history/` branch. Pick a name for that integration and date, then run this from
the branch being merged:

```bash
git push origin HEAD:refs/heads/history/my-integration
```

Link that branch in the PR before squashing. Keep the archive when deleting the working branch.

Merging to `main` does not publish a release. The maintainer opens **Actions → Release → Run
workflow**, selects `main`, and chooses the version bump. `auto` reads conventional commits,
including `!` and `BREAKING CHANGE:` markers in the squash message. Select **Dry run** to build
the candidate package without publishing tags, images, packages or docs.

A real release runs CI, builds the app images, renders a CPU smoke film in the exact amd64 image,
and publishes the tested multi-architecture image before the GitHub release and PyPI packages.
The package build must also pass before the Git tag is pushed. Release runs execute one at a time.

### Images without a release

For a merged container fix, dispatch **Actions → Release → Run workflow** on `main` and select
**app_only**. It runs CI, builds the main/render app image for both architectures, and renders
the smoke film before publishing `ghcr.io/sam-dumont/immich-video-memory-generator:sha-<12-character-commit>`.
Pin that image by digest in your deployment.

Select **inference_only** instead for the standalone inference images. Choose one image-only
mode per run. These modes publish commit tags; they create no GitHub or PyPI release, do not
move `latest`, and do not deploy the docs site.

### Release candidates

The **Channel** input picks what a run publishes. `stable` (the default) is a final release; `rc`
is a release candidate, tagged `vX.Y.Z-rc.N`.

1. **Open a series.** Run with channel `rc` and choose the version bump for the candidate series. The workflow calculates and displays the candidate tag.
2. **Fix and repeat.** Merge fixes to `main`, then run with channel `rc` again: `v1.0.0-rc.2`,
   `rc.3` and so on. The bump input is ignored while a series is open. A run with no commit
   since the last candidate fails instead of publishing a duplicate.
3. **Promote.** Run with channel `stable`. It publishes `v1.0.0` from `main`, with notes covering the candidate series. The run fails if `main` gained a `feat`, `fix`,
   `perf`, `refactor`, `build`, `revert` or breaking commit since the last candidate: that code was
   in no candidate, so cut one more first. Docs, tests, CI and chores do not block promotion.

A candidate goes through the same CI, smoke film and approval gates as a final, and differs in
what it moves:

| | Candidate | Final |
|---|---|---|
| GitHub release | marked pre-release, not "Latest" | marked "Latest" |
| App image | `:1.0.0-rc.1` only | `:1.0.0` and `:latest` |
| Inference images | `:1.0.0-rc.1`, `:1.0.0-rc.1-cuda` | also `:latest`, `:latest-cuda` |
| PyPI | `1.0.0rc1`, installed only with `pip install --pre` | default install |
| Docs site | not deployed | deployed |

Testers pin the exact candidate tag. Candidates do not move `latest`; a final release does.

CI uses `make secret-scan` for both PRs and release runs: all commits since the latest version
tag, or all history for the first release. It also catches secrets removed by a later commit in
that range. Install Gitleaks 8.24.3 to run the same scan locally; pre-commit uses that version too.

## Household validation before release

Before publishing the first RC, recheck the maintainer's eight test households across different family setups. Record the exact candidate revision, the scenarios checked and any failures. Check people and saved groups, selection, titles and wording, and the holidays or celebrations relevant to each household. Fix failures or state the remaining limits before publishing.

This is a release validation requirement, not a claim that eight households cover every family or culture. New examples from contributors should extend that coverage. See [Households and cultures](./development-setup.md#households-and-cultures).

## Private terms gate

`make privacy-gate` blocks owner-defined private terms (family names, birth dates, GPS
coordinates) from diffs, commit messages and PR titles. Two pre-commit hooks run it as well.

The denylist never lives in this repo. It resolves from, in order: `--terms-file`, an env var named
by `--terms-env` (how CI reads the `PRIVATE_TERMS` secret), `$IMMICH_MEMORIES_PRIVATE_TERMS` (a
path), or `~/.config/immich-memories/private-terms.txt`. One term per line, `#` comments ignored, a
`re:` prefix for a regex. With none of those configured the gate prints a notice and exits clean,
which is the normal case for a contributor. Matches are masked to their first character, so a hit
report never contains the term it found.
