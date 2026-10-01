# Immich Memories

[![CI](https://github.com/sam-dumont/immich-video-memory-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/sam-dumont/immich-video-memory-generator/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/sam-dumont/immich-video-memory-generator/graph/badge.svg)](https://codecov.io/gh/sam-dumont/immich-video-memory-generator)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/sam-dumont/immich-video-memory-generator/badge)](https://scorecard.dev/viewer/?uri=github.com/sam-dumont/immich-video-memory-generator)
[![Release](https://github.com/sam-dumont/immich-video-memory-generator/actions/workflows/release.yml/badge.svg)](https://github.com/sam-dumont/immich-video-memory-generator/actions/workflows/release.yml)
[![Python](https://img.shields.io/pypi/pyversions/immich-memories)](https://pypi.org/project/immich-memories/)
[![License](https://img.shields.io/github/license/sam-dumont/immich-video-memory-generator)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-Docusaurus-blue)](https://sam-dumont.github.io/immich-video-memory-generator/)

**Turn your Immich photos and videos into memory films.**

Pick a month, a year, a trip or a person, review the cut, then render with titles and music.

<p align="center">
  <a href="https://sam-dumont.github.io/immich-video-memory-generator/demo/demo.mp4">
    <img src="https://sam-dumont.github.io/immich-video-memory-generator/img/demo-hero.gif" alt="Choose a memory, review and change its cut, and watch the finished film" width="720" height="405">
  </a>
  <br/>
  <sub><a href="https://sam-dumont.github.io/immich-video-memory-generator/demo/demo.mp4">▶ Play the demo with music</a> · <a href="https://sam-dumont.github.io/immich-video-memory-generator/demo/trip-preview.mp4">Watch a finished trip film</a> · CC0 stock pictures, <a href="tests/e2e/fixtures/library/CREDITS.md">credited here</a> · <a href="https://sam-dumont.github.io/immich-video-memory-generator/docs/">Documentation</a></sub>
</p>

## Make your first film

Start with [Quick start](https://sam-dumont.github.io/immich-video-memory-generator/docs/get-started/quick-start), then [Your first film](https://sam-dumont.github.io/immich-video-memory-generator/docs/get-started/first-film). You need Immich v2 or v3, its API key, Docker Compose v2 and 4 GB of RAM for this container. One container is enough; a GPU and a text model are optional.

The app groups photos and videos into moments, picks shots and keeps them in time order. You review the cut before rendering: remove a shot, trim a video or swap a picture. [How it chooses](https://sam-dumont.github.io/immich-video-memory-generator/docs/how-it-chooses/overview) explains the idea.

## After your first film

- [Improve a film](https://sam-dumont.github.io/immich-video-memory-generator/docs/make/improve-a-film): change the length, fix missing people or replace a shot.
- [Titles, maps and music](https://sam-dumont.github.io/immich-video-memory-generator/docs/make/titles-maps-music): choose how it looks and sounds.
- [Automate it](https://sam-dumont.github.io/immich-video-memory-generator/docs/make/automate): let it make films for you.
- [Optional upgrades](https://sam-dumont.github.io/immich-video-memory-generator/docs/better/overview): add captions, model refinement or faster rendering.

## Run it your way

[Operate and configure](https://sam-dumont.github.io/immich-video-memory-generator/docs/run/overview) covers Docker, NAS, Kubernetes, authentication, storage and backups. The default UI listens on localhost with authentication off. Enable authentication before exposing it. Run one UI replica.

A default film talks to your Immich server. Originals are never modified, and uploading a finished film back is opt-in. Maps and external model services need separate configuration. [Privacy](https://sam-dumont.github.io/immich-video-memory-generator/docs/run/privacy) lists what leaves your network.

## Families and cultures

I built this from my life as a white, middle-aged Belgian man in a heteronormative family. The goal is to support all households; the holiday defaults currently reflect Western Europe. Different family setups and cultural calendars are welcome. [Share an example and help check the result](https://sam-dumont.github.io/immich-video-memory-generator/docs/contribute/development-setup#households-and-cultures).

## Development

`make dev` installs everything, `make ci` runs the checks, and `make help` lists the rest. See [CONTRIBUTING.md](CONTRIBUTING.md). Claude and Codex write most of the code; I set the direction and test the films on a real library. [DISCLAIMER.md](DISCLAIMER.md) explains the process and its limits.

## License

MIT, see [LICENSE](LICENSE).
