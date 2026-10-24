# Immich Memories

[![CI](https://github.com/sam-dumont/immich-memories/actions/workflows/ci.yml/badge.svg)](https://github.com/sam-dumont/immich-memories/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/sam-dumont/immich-memories/graph/badge.svg)](https://codecov.io/gh/sam-dumont/immich-memories)
[![OpenSSF Scorecard](https://img.shields.io/ossf-scorecard/github.com/sam-dumont/immich-memories?label=openssf%20scorecard)](https://scorecard.dev/viewer/?uri=github.com/sam-dumont/immich-memories)
[![Release](https://github.com/sam-dumont/immich-memories/actions/workflows/release.yml/badge.svg)](https://github.com/sam-dumont/immich-memories/actions/workflows/release.yml)
[![Python](https://img.shields.io/pypi/pyversions/immich-memories)](https://pypi.org/project/immich-memories/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-Docusaurus-blue)](https://sam-dumont.github.io/immich-memories/)

**Watch your memories again, in films you can make your own.**

Immich Memories turns the photos and videos in your Immich library into MP4 films with titles
and music. Pick a month, a year, a trip, an album or a person. Review the proposed cut, swap what
you don't like, then render. A quiet month makes a short film rather than 3 minutes of filler.

It runs on a plain NAS with no GPU and no model server. Basic reads the pictures with small local
classifiers, GPU adds picture descriptions and extra checks, and Full adds a text reader that
refines the cut.

**[Quick start](#make-your-first-film)** · **[Documentation](https://sam-dumont.github.io/immich-memories/docs/)** · **[Install guides](https://sam-dumont.github.io/immich-memories/docs/run/overview)** · **[Demo](https://sam-dumont.github.io/immich-memories/demo/demo.mp4)**

<p align="center">
  <a href="https://sam-dumont.github.io/immich-memories/demo/demo.mp4">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://sam-dumont.github.io/immich-memories/img/dark-demo-hero.gif">
      <img src="https://sam-dumont.github.io/immich-memories/img/demo-hero.gif" alt="Choose a memory, review and change its cut, and watch the finished film" width="720">
    </picture>
  </a>
  <br/>
  <sub><a href="https://sam-dumont.github.io/immich-memories/demo/demo.mp4">▶ Play the demo with music</a> · <a href="https://sam-dumont.github.io/immich-memories/demo/trip-preview.mp4">Watch a finished trip film</a> · Wikimedia Commons photographs under CC0 or CC BY, <a href="tests/e2e/fixtures/library/CREDITS.md">credited here</a> · <a href="https://sam-dumont.github.io/immich-memories/docs/">Documentation</a></sub>
</p>

## Make your first film

**Docker Compose is the recommended install. Start with Basic if you are unsure.** Every tier
makes a complete film, and you can change tiers later.

| Tier | What it adds | What it needs | Install |
|---|---|---|---|
| **Basic** | Dates, favourites, people, places and small picture classifiers guide the cut; up to 1080p. | 2 CPU cores and 4 GiB RAM for the app, in addition to Immich. | Follow the steps below. |
| **GPU** | Picture descriptions, document/sensitive-content checks and a family-viewing pre-screen. | NVIDIA services with the Container Toolkit, or native Apple Silicon. Allow 8 GiB for the Compose app plus its model services. | Select **GPU** in [Quick start](https://sam-dumont.github.io/immich-memories/docs/get-started/quick-start), or use [native Mac](https://sam-dumont.github.io/immich-memories/docs/run/uv-pip#apple-silicon). |
| **Full** | A text reader refines the cut. | The GPU setup plus an enabled reader with a 32k context window. | Select **Full** in [Quick start](https://sam-dumont.github.io/immich-memories/docs/get-started/quick-start). |

You need an existing Immich server (2.7.5 or later on v2, 3.2.4 or later on v3), Docker Compose v2
and disk space: about 25 GB of app data plus 0.35 GB per 1,000 pictures and videos in your
library, plus the images and your finished films. The
[deployment matrix](https://sam-dumont.github.io/immich-memories/docs/run/tested-deployments)
records what has been tested. GPU services can run on another machine. On a NAS container
manager, [use its platform guide](https://sam-dumont.github.io/immich-memories/docs/run/nas).

1. **Download the two Basic files** into a new folder:

   ```bash
   mkdir -p immich-memories && cd immich-memories
   VERSION=1.0.0-rc.12
   curl -fLO "https://github.com/sam-dumont/immich-memories/releases/download/v${VERSION}/docker-compose.yml"
   curl -fLO "https://github.com/sam-dumont/immich-memories/releases/download/v${VERSION}/example.env"
   cp example.env .env
   ```

   `example.env` pins the app image to the same release. Keep `TIER=basic`.

2. **Edit `.env`** with your Immich address, API key and timezone:

   ```ini
   IMMICH_URL=http://192.168.1.10:2283
   IMMICH_API_KEY=your-api-key
   TZ=Etc/UTC
   ```

   In Immich, create the key under **Account Settings → API Keys** with the
   [ten read permissions](https://sam-dumont.github.io/immich-memories/docs/run/docker#the-api-key).
   Use an Immich address the container can reach; `localhost` means the container itself.

   To open the app from another computer on your LAN, also set this in `.env`:

   ```ini
   UI_BIND_ADDRESS=0.0.0.0
   ```

   The app has its own login, separate from Immich. If you set none, the first start generates one
   (step 4). To choose your own, add `IMMICH_MEMORIES_AUTH_USERNAME` and
   `IMMICH_MEMORIES_AUTH_PASSWORD` (at least 12 characters). LAN access uses HTTP; [HTTPS setup](https://sam-dumont.github.io/immich-memories/docs/run/authentication#behind-a-reverse-proxy-with-tls)
   is separate. Otherwise, keep the default localhost binding.

3. **Prepare the output folder and start the app.** On Linux:

   ```bash
   mkdir -p output
   sudo chown 1000:1000 output
   chmod 600 .env
   docker compose up -d
   ```

   The app writes films as UID/GID 1000. For a Synology bind mount, use the
   [DSM folder permissions](https://sam-dumont.github.io/immich-memories/docs/run/nas#the-output-folder)
   instead of `chown`.

4. **Open the app** at `http://localhost:22830`, or `http://your-server-address:22830` for LAN
   access. Sign in as `admin` with the generated password, printed once in
   `docker logs immich-memories` (or use the login you set). On **Memory**, click **Download models**
   and wait for the card to disappear. No card means the files are already there.

   Make [your first film](https://sam-dumont.github.io/immich-memories/docs/get-started/first-film)
   from an album of **20–50 photos and short videos**: choose **Album**, set the length to
   **0.5 minutes**, then **Cut**, review and **Render**. Leave upload off and use **Download film**
   to keep the MP4. A full month can take hours to prepare on a NAS; a small album gets you a film
   first.

For a failed step, use [Installation help](https://sam-dumont.github.io/immich-memories/docs/reference/installation-help).
Once the first film works, [After install](https://sam-dumont.github.io/immich-memories/docs/get-started/after-install)
covers home, people, language, backups and automation.

## What you can do

- **Photos and videos in one film.** Stills get animated, videos give their best few seconds,
  and a Live Photo plays as motion when its clip lasts at least 2.5 s and actually moves. Favourites and
  named people win close calls. Every shot says why it's in the cut, and the pool shows
  everything that was left out.
- **Change the cut before rendering.** Remove a shot, trim a video, swap a picture or pull one
  in from the pool, then render that revision. "Never use" is a lasting decision, separate from
  dropping a shot from one film.
- **Titles and music out of the box.** A film is titled by what it is and when, in the film's
  language: "Summer 2025", "Kit's birthday · 2026", "Kit & Pat · 2025", "Christmas ·
  2019–2025". Those are the app's own titles, never a model's. Model-written titles and
  summaries are an experimental opt-in (`--llm-title`).
  Every film gets a bundled track, or your own music folder. Maps and generated music are
  optional extras with their own setup.
- **Automate it later.** A daily timer picks one memory worth making (a trip, a birthday, last
  month) and can upload it to Immich, with its title and story summary as the description, or
  keep it on disk. Tags for the type, years and stories are opt-in (`upload.film_tags`). Make a
  few films by hand first.
- **Ask in your own words.** "our cat through the years" can become a film. Highly
  experimental: tuned on one real library, so preview before you trust it.
- **Add a GPU or a model when you want.** Basic makes complete films on a CPU. A GPU adds
  captions and extra picture checks, Full adds a text reader on top. A hardware encoder speeds
  up rendering and changes nothing about which pictures make the cut.

[How it chooses](https://sam-dumont.github.io/immich-memories/docs/how-it-chooses/overview)
explains the selection rules. [Improve a film](https://sam-dumont.github.io/immich-memories/docs/make/improve-a-film)
covers length, missing people and shot changes. What doesn't work yet is in the
[issue tracker](https://github.com/sam-dumont/immich-memories/issues).

## Access and privacy

The app talks to Immich with a scoped API key and never modifies your originals. Uploading a
film is opt-in. There is no telemetry, and the update check only runs when you ask for it.
Model downloads, optional model servers, maps, notifications and workers each have their own
data flow, and a local URL alone doesn't prove nothing leaves.
[Privacy](https://sam-dumont.github.io/immich-memories/docs/run/privacy) lists every recipient
and how to check the Basic tier is offline.

**Sign-in is on by default.** The first start generates a password: find it in the container log
(`docker logs immich-memories`). Lost it? `immich-memories auth reset-password` makes a new one. Native installs
and the shipped Compose file listen on localhost only; change the port mapping and the sign-in
is what stands between your LAN and your library. [Operate and configure](https://sam-dumont.github.io/immich-memories/docs/run/overview)
covers login, NAS/Kubernetes setup, backups and storage. Keep one UI replica.
Report vulnerabilities as [SECURITY.md](SECURITY.md) describes.

This is an independent companion to Immich, not made or endorsed by the Immich team.

## People and calendars

Families, relationships and calendars differ a lot, and this doesn't cover them all.
If yours is missing, say so. [Calendar limits](https://sam-dumont.github.io/immich-memories/docs/reference/film-types#holiday)
and [contributing household examples](https://sam-dumont.github.io/immich-memories/docs/contribute/development-setup#households-and-cultures)
show where help is useful.

## Development

Claude and Codex write most of the code; I set the direction and test films on a real library.
`make dev` installs the development tools and `make ci` runs the checks.
[CONTRIBUTING.md](CONTRIBUTING.md) describes the process;
[DISCLAIMER.md](DISCLAIMER.md) describes its limits.

## License

MIT, see [LICENSE](LICENSE).
