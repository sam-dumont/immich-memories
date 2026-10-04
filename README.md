# Immich Memories

[![CI](https://github.com/sam-dumont/immich-memories/actions/workflows/ci.yml/badge.svg)](https://github.com/sam-dumont/immich-memories/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/sam-dumont/immich-memories/graph/badge.svg)](https://codecov.io/gh/sam-dumont/immich-memories)
[![OpenSSF Scorecard](https://img.shields.io/ossf-scorecard/github.com/sam-dumont/immich-memories?label=openssf%20scorecard)](https://scorecard.dev/viewer/?uri=github.com/sam-dumont/immich-memories)
[![Release](https://github.com/sam-dumont/immich-memories/actions/workflows/release.yml/badge.svg)](https://github.com/sam-dumont/immich-memories/actions/workflows/release.yml)
[![Python](https://img.shields.io/pypi/pyversions/immich-memories)](https://pypi.org/project/immich-memories/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-Docusaurus-blue)](https://sam-dumont.github.io/immich-memories/)

**Watch your memories again, in films you can make your own.**

Immich Memories is a self-hosted companion that turns photos and videos from your Immich
library into finished MP4 memory films. Choose the material, review the proposed cut, change
its shots, then render with titles and music. You decide what belongs in the film before it
spends time rendering it.

Pick a month, a year, a trip, an album or a person. The app reads Immich's dates, favourites,
people and locations, groups related photos and videos into moments, and proposes shots in
time order. The cut includes the chosen pictures and video intervals, with explanations you
can inspect. A quiet period can produce a shorter film instead of stretching it to fill time.

<p align="center">
  <a href="https://sam-dumont.github.io/immich-memories/demo/demo.mp4">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://sam-dumont.github.io/immich-memories/img/dark-demo-hero.gif">
      <img src="https://sam-dumont.github.io/immich-memories/img/demo-hero.gif" alt="Choose a memory, review and change its cut, and watch the finished film" width="720">
    </picture>
  </a>
  <br/>
  <sub><a href="https://sam-dumont.github.io/immich-memories/demo/demo.mp4">▶ Play the demo with music</a> · <a href="https://sam-dumont.github.io/immich-memories/demo/trip-preview.mp4">Watch a finished trip film</a> · CC0 stock pictures, <a href="tests/e2e/fixtures/library/CREDITS.md">credited here</a> · <a href="https://sam-dumont.github.io/immich-memories/docs/">Documentation</a></sub>
</p>

The first demo is a recording of the interface: choosing a memory, reviewing it and making
changes. The trip link shows a finished film. Both use cleared public media, with credits
linked above; they are examples of the workflow and output, not private household footage.

## What you can do

- **Use photos and videos together.** Stills become animated shots; videos contribute selected
  intervals. Live Photos can keep their motion. Favourites and named people help the app
  choose among similar moments, and you can inspect what was left in the pool.
- **Change the cut before rendering.** Remove a shot, trim a video, replace a picture or add
  one from the pool. Save a revision and render that revision. A lasting “Never use” decision
  is separate from removing something from one film.
- **Add titles and music.** Start with the default titles and bundled tracks. Choose the format
  and soundtrack when the cut looks right. Maps and generated music have their own setup and
  costs; neither is required for a first film.
- **Make it automatic later.** The optional daily timer can suggest and produce eligible
  memories. You choose whether finished films remain local or upload to Immich. Run one
  scheduler, and check the results before treating it as unattended housekeeping.
- **Add local models or GPU services.** Basic already makes complete films on a CPU. GPU adds
  captions and extra picture checks; Full adds a text reader's refinement. A hardware encoder
  speeds rendering separately. Each service has its own memory and privacy requirements.

[How it chooses](https://sam-dumont.github.io/immich-memories/docs/how-it-chooses/overview)
explains the selection rules. [Improve a film](https://sam-dumont.github.io/immich-memories/docs/make/improve-a-film)
covers length, missing people and shot changes without a list of configuration switches.

## Make your first film

The default is **one prebuilt Docker app container**, beside your existing Immich installation.
No GPU, hosted model account or caption server is required. You need Docker Compose v2, two
CPU cores, **4 GiB RAM for this app in addition to Immich and the host**, and **25 GB for app
data plus images and finished output**. The app handles Immich v2 and v3 API contracts;
[the compatibility and deployment matrix](https://sam-dumont.github.io/immich-memories/docs/run/tested-deployments)
distinguishes tested versions and topologies from unverified ones.

Cold setup downloads the image and model files, then prepares the pictures you select. A real
month can take hours on a NAS. Start with **20–50 photos/videos and a requested 30-second film**;
a short output alone does not reduce the preparation pool.
[Phase progress and measured costs](https://sam-dumont.github.io/immich-memories/docs/get-started/first-film#progress-and-recovery)
explain what is happening and where to look when it stops.

Use the [release-matching quick start](https://sam-dumont.github.io/immich-memories/docs/get-started/quick-start),
then [Your first film](https://sam-dumont.github.io/immich-memories/docs/get-started/first-film).
The documentation's version must match its prebuilt downloads. A development preview without
matching assets says so; an older package does not validate that preview's instructions.
The first trial keeps upload off and ends with a playable local file you can download.

## Access and privacy

The app connects to Immich with a scoped API key; originals are not modified. Uploading a
finished film is opt-in. Model preparation needs download access, and optional model servers,
maps, notifications and workers have separate data flows. A local URL alone is not proof of
offline operation. [Privacy](https://sam-dumont.github.io/immich-memories/docs/run/privacy)
lists recipients and the Basic offline verification procedure.

**Enable authentication before LAN access.** Authentication is disabled by default. Native installs and the shipped Compose mapping
start on localhost. Publishing a different Docker port mapping can expose the app, including
its access to your library. [Operate and configure](https://sam-dumont.github.io/immich-memories/docs/run/overview)
covers login, NAS/Kubernetes setup, backups and storage. Keep one UI replica.
Report vulnerabilities as [SECURITY.md](SECURITY.md) describes.

This is a separate companion project for Immich, with no upstream ownership or endorsement implied.

## People and calendars

The aim is to include different people, relationships and cultures; feedback about missing
cases is welcome. [Calendar limits](https://sam-dumont.github.io/immich-memories/docs/reference/special-days)
and [contributing household examples](https://sam-dumont.github.io/immich-memories/docs/contribute/development-setup#households-and-cultures)
show where help is useful.

## Development

Claude and Codex write most of the code; I set the direction and test films on a real library.
`make dev` installs the development tools and `make ci` runs the checks.
[CONTRIBUTING.md](CONTRIBUTING.md) describes the process;
[DISCLAIMER.md](DISCLAIMER.md) describes its limits.

## License

MIT, see [LICENSE](LICENSE).
