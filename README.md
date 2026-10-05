# Immich Memories

[![CI](https://github.com/sam-dumont/immich-memories/actions/workflows/ci.yml/badge.svg)](https://github.com/sam-dumont/immich-memories/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/sam-dumont/immich-memories/graph/badge.svg)](https://codecov.io/gh/sam-dumont/immich-memories)
[![OpenSSF Scorecard](https://img.shields.io/ossf-scorecard/github.com/sam-dumont/immich-memories?label=openssf%20scorecard)](https://scorecard.dev/viewer/?uri=github.com/sam-dumont/immich-memories)
[![Release](https://github.com/sam-dumont/immich-memories/actions/workflows/release.yml/badge.svg)](https://github.com/sam-dumont/immich-memories/actions/workflows/release.yml)
[![Python](https://img.shields.io/pypi/pyversions/immich-memories)](https://pypi.org/project/immich-memories/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-Docusaurus-blue)](https://sam-dumont.github.io/immich-memories/)

**Watch your memories again, in films you can make your own.**

Immich Memories turns the photos and videos in your Immich library into finished MP4 memory
films. Pick a month, a year, a trip, an album or a person. It reads Immich's dates, favourites,
people and places, groups pictures into moments and proposes a cut in time order, with the
reason each shot is there. You review it, swap what you don't like, then render with titles and
music. A quiet month makes a short film rather than 3 minutes of filler.

It runs on a plain NAS with no GPU and no model. A GPU or a model makes it better.

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

The first link is a screen recording of the app, the second a finished trip film. Both use
CC0 stock pictures, never anyone's family.

## What you can do

- **Photos and videos in one film.** Stills get animated, videos give their best few seconds,
  Live Photos keep their motion. Favourites and named people win close calls, and you can see
  everything that was left in the pool.
- **Change the cut before rendering.** Remove a shot, trim a video, swap a picture or pull one
  in from the pool, then render that revision. "Never use" is a lasting decision, separate from
  dropping a shot from one film.
- **Titles and music out of the box.** Bundled tracks and template titles work on day one.
  Maps and generated music are optional extras with their own setup.
- **Automate it later.** A daily timer picks one memory worth making (a trip, a birthday, last
  month) and can upload it to Immich or keep it on disk. Make a few films by hand first.
- **Ask in your own words.** "our cat through the years" can become a film. Highly
  experimental: tuned on one real library, so preview before you trust it.
- **Add a GPU or a model when you want.** Basic makes complete films on a CPU. A GPU adds
  captions and extra picture checks, Full adds a text reader on top. A hardware encoder only
  speeds up rendering.

[How it chooses](https://sam-dumont.github.io/immich-memories/docs/how-it-chooses/overview)
explains the selection rules. [Improve a film](https://sam-dumont.github.io/immich-memories/docs/make/improve-a-film)
covers length, missing people and shot changes. [Known limitations](https://sam-dumont.github.io/immich-memories/docs/how-it-chooses/known-limitations)
lists what doesn't work yet.

## Make your first film

The default is **one prebuilt Docker container** next to your existing Immich. No GPU, no hosted
model account, no caption server. You need Docker Compose v2, two CPU cores, **4 GiB RAM for
this app on top of Immich**, and **25 GB for app data, images and finished films**. Immich v2 and
v3 both work; [the deployment matrix](https://sam-dumont.github.io/immich-memories/docs/run/tested-deployments)
says which versions and setups were actually tested.

The first run downloads the image and model files, then prepares the pictures you pick. A full
month can take hours on a NAS, so start with **20–50 photos/videos and a 30-second film**. A short
film alone doesn't shrink the preparation: pick a short period too.
[Progress and recovery](https://sam-dumont.github.io/immich-memories/docs/get-started/first-film#progress-and-recovery)
shows each phase and where to look when it stops.

Follow the [quick start](https://sam-dumont.github.io/immich-memories/docs/get-started/quick-start),
then [Your first film](https://sam-dumont.github.io/immich-memories/docs/get-started/first-film).
Use the docs that match your release: a development preview says so when its downloads don't
exist yet. Upload stays off on the first run, and you end with a local file you can play.

## Access and privacy

The app talks to Immich with a scoped API key and never modifies your originals. Uploading a
film is opt-in. Model downloads, optional model servers, maps, notifications and workers each
have their own data flow, and a local URL alone doesn't prove nothing leaves.
[Privacy](https://sam-dumont.github.io/immich-memories/docs/run/privacy) lists every recipient
and how to check the Basic tier is offline.

**Turn on authentication before you open it to your LAN.** It's off by default. Native installs
and the shipped Compose file listen on localhost only; change the port mapping and anyone who
can reach it can read your library through it. [Operate and configure](https://sam-dumont.github.io/immich-memories/docs/run/overview)
covers login, NAS/Kubernetes setup, backups and storage. Keep one UI replica.
Report vulnerabilities as [SECURITY.md](SECURITY.md) describes.

This is an independent companion to Immich, not made or endorsed by the Immich team.

## People and calendars

Families, relationships and calendars differ a lot, and the test households only cover some of
them. If yours is missing, say so. [Calendar limits](https://sam-dumont.github.io/immich-memories/docs/reference/special-days)
and [contributing household examples](https://sam-dumont.github.io/immich-memories/docs/contribute/development-setup#households-and-cultures)
show where help is useful.

## Development

Claude and Codex write most of the code; I set the direction and test films on a real library.
`make dev` installs the development tools and `make ci` runs the checks.
[CONTRIBUTING.md](CONTRIBUTING.md) describes the process;
[DISCLAIMER.md](DISCLAIMER.md) describes its limits.

## License

MIT, see [LICENSE](LICENSE).
