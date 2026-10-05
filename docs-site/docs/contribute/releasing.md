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
the smoke film before publishing `ghcr.io/sam-dumont/immich-memories:sha-<12-character-commit>`.
Pin that image by digest in your deployment.

Select **inference_only** instead for the standalone inference images. Choose one image-only
mode per run. These modes publish commit tags; they create no GitHub or PyPI release, do not
move `latest`, and do not deploy the docs site.

### Pre-tag onboarding rehearsal

Use **Channel: dev** on `main` to publish a complete pre-tag rehearsal without opening the RC
series. It produces `v0.0.0-dev.RUN_ID`: matching app/inference image tags, a native wheel,
Compose files, a deployment bundle, `installation.json` and `SHA256SUMS`. It uses the same CI,
image smoke, approval and provenance steps as releases. It does not publish to PyPI or move
`latest`; native setup exports install the wheel from the exact GitHub release URL.

The docs build and setup builder use that exact rehearsal version. Publication waits for the
matching images/bundle before deploying docs. `installation.json` records the source SHA and
published image manifests/digests, including architectures. The checksum list covers the wheel,
deployment files and identity record. Model-only tags are not application versions.
A rehearsal rerun is refused before building: dispatch a new run to avoid replacing published
candidate identities. Dispatching this workflow is a separate publication action from merging
its implementation.

Run the prebuilt first-install checks
against these public inputs. Record anonymous pulls, exact host/service/Immich versions, cold
versus warm state and the bounded playable film. Publishing artifacts alone is not acceptance.
After RC tagging, verify the actual RC identities/links and rerun affected lanes if runtime
artifacts differ. Check Pages, release downloads and GHCR separately after a repository rename;
a GitHub redirect does not prove a Pages redirect. GHCR keeps the documented package name.

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
| Docs site | root before the first 1.x final; `/next` afterward, preserving the final site | root |

Testers pin the exact candidate tag. Candidates do not move `latest`; a final release does.

CI uses `make secret-scan` for both PRs and release runs: all commits since the latest version
tag, or all history for the first release. It also catches secrets removed by a later commit in
that range. Install Gitleaks 8.24.3 to run the same scan locally; pre-commit uses that version too.

## Household validation before release

Before the first RC, validate the exact candidate revision against the private test households. Check people/groups, selection, titles, wording and relevant celebrations, including expected no-film outcomes. Report the tiers actually checked; an older report does not validate the candidate.

Private validation media and detailed reports stay private. Publish only anonymous aggregate results. Public screenshots and demos use the separate [CC0 demo fixture](./demo-assets.md#fixture-and-asset-contracts).

The private households do not cover every family or culture. Contributor examples help extend that coverage; see [Households and cultures](./development-setup.md#households-and-cultures).

## Private terms gate

`make privacy-gate` blocks owner-defined private terms (family names, birth dates, GPS
coordinates) from diffs, commit messages and PR titles. Two pre-commit hooks run it as well.

The denylist never lives in this repo. It resolves from, in order: `--terms-file`, an env var named
by `--terms-env` (how CI reads the `PRIVATE_TERMS` secret), `$IMMICH_MEMORIES_PRIVATE_TERMS` (a
path), or `~/.config/immich-memories/private-terms.txt`. One term per line, `#` comments ignored, a
`re:` prefix for a regex. With none of those configured the gate prints a notice and exits clean,
which is the normal case for a contributor. Matches are masked to their first character, so a hit
report never contains the term it found.

## Build versions

Release builds stamp the selected version into the wheel, container labels and docs.
The app displays the packaged server version. Docs show their build version in the
navigation, footer and page metadata; `/next/` also includes it in the banner.
Release candidates keep their exact `vX.Y.Z-rc.N` tag. Unreleased builds include
the source commit, and version discovery ignores the separate `models-v*` tags.

## Repository name and search indexing

The repository is `sam-dumont/immich-memories`. The package and command remain
`immich-memories`. Container images use `ghcr.io/sam-dumont/immich-memories`
and `ghcr.io/sam-dumont/immich-memories/inference`. CPU tags are `X.Y.Z` and
`latest`; CUDA inference tags add `-cuda`. Model downloads use the renamed
repository with the same release tags, filenames and checksums.

A repository rename does not copy container tags. Run **Migrate Container Images**
on `main` to copy the existing `0.103.0` app, inference CPU and inference CUDA
manifests to the new packages, including their `latest` aliases. The workflow
checks source and destination digests and refuses to replace a different image.
It shares the release publication lock, so it cannot race a release.

After the first copy, set both new container packages to **Public** in their
GitHub package settings, then check that they can be pulled without signing in.
GHCR creates new packages as private, even for public repositories.
[GitHub package visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).

Old container packages remain available for existing installations and historical
releases. To switch an installation, download the current Compose files or change
its image repository to the new name, keeping its version tag. Historical build
attestations retain the original repository and signer identity; copying an image
does not create new build provenance. See [Security](https://github.com/sam-dumont/immich-memories/blob/main/SECURITY.md).

Before the next PyPI release, check the trusted publisher for **both**
`immich-memories` and `immich-memories-music`: owner `sam-dumont`, repository
`immich-memories`, workflow `release.yml`, environment `pypi`. Replace the old
publisher after adding the new one. [PyPI publisher setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

The free docs address is `https://sam-dumont.github.io/immich-memories/`.
Docusaurus renders HTML, canonical links and `sitemap.xml`; each production build
checks the sitemap pages. Candidate docs under `/next/` are marked `noindex`.

To verify indexing in [Google Search Console](https://search.google.com/search-console):

1. Add a **URL prefix** property for `https://sam-dumont.github.io/immich-memories/`.
2. Choose **HTML tag** verification. Save just the tag's `content` value as the
   GitHub Actions repository variable `GOOGLE_SITE_VERIFICATION`.
3. Run **Deploy Docs** on `main`, then click **Verify** in Search Console. Keep the variable for future builds.
4. Submit `https://sam-dumont.github.io/immich-memories/sitemap.xml`.
5. Inspect the homepage and quick-start URL, run the live test, and request indexing.
   Check the Page indexing report after Google has crawled them.

A `robots.txt` inside this project's subdirectory would not control crawling:
Google reads it at `https://sam-dumont.github.io/robots.txt`. No file is required
to allow crawling. [Google's robots.txt rules](https://developers.google.com/crawling/docs/robots-txt/create-robots-txt).

GitHub redirects old repository links, but not the old Pages path. Update links
you control. Do not recreate the old repository to host redirects: it would
replace GitHub's repository redirects. Preserving the old docs paths needs a
separate redirect setup at the account site. [GitHub rename behavior](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).

Google decides whether and when to index a page. Submitting a sitemap or an
indexing request does not guarantee inclusion or ranking. The GitHub repository
itself is on GitHub's domain; this Search Console property covers the docs only.
