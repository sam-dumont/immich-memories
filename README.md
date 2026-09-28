# Immich Memories

[![CI](https://github.com/sam-dumont/immich-video-memory-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/sam-dumont/immich-video-memory-generator/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/sam-dumont/immich-video-memory-generator/graph/badge.svg)](https://codecov.io/gh/sam-dumont/immich-video-memory-generator)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/sam-dumont/immich-video-memory-generator/badge)](https://scorecard.dev/viewer/?uri=github.com/sam-dumont/immich-video-memory-generator)
[![Release](https://github.com/sam-dumont/immich-video-memory-generator/actions/workflows/release.yml/badge.svg)](https://github.com/sam-dumont/immich-video-memory-generator/actions/workflows/release.yml)
[![Python](https://img.shields.io/pypi/pyversions/immich-memories)](https://pypi.org/project/immich-memories/)
[![License](https://img.shields.io/github/license/sam-dumont/immich-video-memory-generator)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-Docusaurus-blue)](https://sam-dumont.github.io/immich-video-memory-generator/)

**Your self-hosted [Immich](https://immich.app/) library, cut into films worth keeping: a month, a year in review, a trip with its map, one person across the years.**

<p align="center">
  <a href="https://sam-dumont.github.io/immich-video-memory-generator/demo/demo.mp4">
    <img src="https://sam-dumont.github.io/immich-video-memory-generator/img/demo-hero.gif" alt="Choose a memory, review and change its cut, and watch the finished film" width="720" height="405">
  </a>
  <br/>
  <sub><a href="https://sam-dumont.github.io/immich-video-memory-generator/demo/demo.mp4">▶ Play the demo with music</a> · <a href="https://sam-dumont.github.io/immich-video-memory-generator/demo/trip-preview.mp4">Watch a finished trip film</a> · CC0 stock pictures, <a href="tests/e2e/fixtures/library/CREDITS.md">credited here</a> · <a href="https://sam-dumont.github.io/immich-video-memory-generator/docs/">Documentation</a></sub>
</p>

It reads a period of your library, picks the pictures and videos that tell it, keeps them in the order they were taken, and renders the film with titles, maps and music. Before anything renders you get the cut as a contact sheet: open a picture to read why it stayed, remove it, trim it, swap it for another shot of the same moment, then render.

## Works on a plain NAS, better with a GPU or a model

The default install is one container next to Immich. It cuts from what your library already knows (dates, places, favourites, the people Immich recognised) plus a few small classifiers on the CPU, and that makes a film worth sharing.

A GPU adds a caption for every picture in the cut and a second family-viewing check, and speeds up reading the pictures. A text model on top of that polishes the cut: it reads the draft and swaps out the shots that add nothing. It also writes the title and picks the music. Feature by feature: [what a GPU or a model adds](https://sam-dumont.github.io/immich-video-memory-generator/docs/get-started/what-a-gpu-or-a-model-adds).

## Run it

You need Docker with Compose v2, Immich v2 or v3, and 4 GB of RAM for this container.

```bash
mkdir immich-memories && cd immich-memories
curl -O https://raw.githubusercontent.com/sam-dumont/immich-video-memory-generator/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/sam-dumont/immich-video-memory-generator/main/example.env
cp example.env .env && mkdir output
# set IMMICH_URL and IMMICH_API_KEY in .env
docker compose up -d
docker compose exec immich-memories immich-memories models fetch   # the CPU classifiers, about 130 MB, once
```

Open http://localhost:8080, pick **Monthly Highlights**, a month, and press **Cut**. The [Quick start](https://sam-dumont.github.io/immich-video-memory-generator/docs/get-started/quick-start) walks it step by step, and [Teach it your family](https://sam-dumont.github.io/immich-video-memory-generator/docs/get-started/who-is-who) covers the two settings that make the cut good: where home is, and who is who. Without Docker: [pip / uv](https://sam-dumont.github.io/immich-video-memory-generator/docs/run/uv-pip).

The port is published on localhost only and authentication is disabled by default. The app holds an API key to your whole library, so turn on [authentication](https://sam-dumont.github.io/immich-video-memory-generator/docs/run/authentication) before you expose it. The UI is single-user, single-replica: run one instance.

### Immich v2 and v3

Both majors work, Immich v2 and v3, detected at runtime:

```yaml
immich:
  api_version: auto  # auto | v2 | v3
```

Leave this on `auto`. The app detects the server major version and uses the matching API contract; you do not choose a version for each run. The explicit `v2` and `v3` values are manual troubleshooting overrides: escape hatches for proxies or unusual deployments that hide or rewrite the version endpoint. They force that contract, so don't use them as upgrade flags.

## What leaves your network

A default run talks to your Immich server and nothing else. No telemetry, no account. Immich stays read-only unless you ask for the film to be uploaded back. Place names and the satellite map for trips sit behind `network:` switches that are off in a fresh install, and a caption or model server only receives anything if you configure one. The full list: [Privacy](https://sam-dumont.github.io/immich-video-memory-generator/docs/run/privacy).

## How it decides

Every rule is written down, with diagrams: [How it chooses](https://sam-dumont.github.io/immich-video-memory-generator/docs/how-it-chooses/overview). The web UI and the CLI run the same editor, and every button shows the command it runs. `immich-memories runs why <asset-id>` says which step kept a picture or left it out.

## What is stable, what still moves

Stable: the install, the read-only use of Immich, and the render (titles, maps, music, HDR, encoding). Still moving: selection, which pictures make the cut. It changes most weeks, and every change is checked against films cut from real libraries before it merges. A new release can pick a slightly different set for the same month, so pin a version tag instead of `latest` if you want it to hold still, and watch a film before you send it to the family.

## Built with AI, on purpose

Claude and Codex write most of the code. I set the direction, rule on what a good film is, and test the films on a real library. The experiment is how far AI can take a codebase this size while it stays clean, and the answer so far is: as far as the gates in the `Makefile` hold. [DISCLAIMER.md](DISCLAIMER.md) says who does what and where it fell short.

## Development

`make dev` installs everything, `make ci` runs what CI runs, `make help` lists the rest. Guidelines in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE).
