---
title: Writing the docs
sidebar_position: 8
---

# Writing the docs

Every page is read by someone trying to do something. If a sentence doesn't help that person
decide, act or understand, it goes.

## Who reads what

| Section | Reader | What belongs there | What doesn't |
|---|---|---|---|
| README | someone who just found the repo | what it makes, one film, one install command, links | measurements, internals |
| Welcome | a newcomer deciding in a minute | what it is, what a film looks like, what it needs | internals, history |
| Get started | a newcomer installing it | a complete path to a first film for each tier | options they don't need yet |
| Make | someone making films | the steps for a task and what you get | why it picks what it picks |
| How it chooses | a user wondering "why these pictures?" | the reasons in plain words, and which setting changes them | file or function names, "used to" |
| Run | the operator | commands, paths, ports, what breaks and how to fix it; one test-status table by release and hardware | selection internals, history |
| Better | someone weighing an add-on | what a GPU, a model, captions or music adds, and what it costs | install trivia that lives in Run |
| Reference | a power user | every setting, every threshold | stories; module names outside selection internals |
| Help pages | someone stuck | symptom, cause, fix | background |
| How this was built | the curious | the story, with its dates | commit hashes |
| Contribute | developers | internal names, tests, CI | private test-household detail |

Go from general to specific on every page and in the sidebar. The plain NAS path comes first;
Basic, GPU and Full must each have a prominent, complete installation path. Keep required
prerequisites beside the step that needs them. Put troubleshooting, operator variants and
acceptance-test procedures in their own pages, linked from the relevant step. Avoid making
readers repeat setup in Quick start, platform guides and After install.

## Never on a public page

- Issue or PR numbers, commit hashes, "added in", "since vX", "used to", "no longer".
- Calendar dates. Two exceptions: example dates in commands, and *How this was built*.
  Measurements in *Measure your setup* name the release and the hardware, not the day.
- Open bugs and limitations. There is no limitations page: what doesn't work yet lives in the
  [issue tracker](https://github.com/sam-dumont/immich-memories/issues), and pages link it.
- Test-household or campaign trivia that doesn't help the reader decide.
- Anything personal: family names, places, dates, asset ids.

Pinned model revisions and image digests stay where an operator needs them to verify a download.

## Diagrams

Draw the kind of diagram the question needs, from the code, never from memory:

| Question | Diagram |
|---|---|
| What are the parts and what talks to what? | architecture (components, and what crosses the network boundary) |
| What runs where for my install? | deployment, one per install path |
| What happens, in order, when I run X? | sequence (`generate`, a scheduled run, `--ask`, a web job) |
| Which option should I pick? / Why was this picture kept? | decision chart |
| What states can a run be in? | state diagram |

Mermaid is available (11.x). Check a new block renders in `make docs-build` before pushing.

## Voice

Write like the owner: direct, specific, real numbers, no chatbot words, no em dashes. AI agents
load the `sams-voice:sams-voice` skill before writing. `make docs-voice` catches the worst of it.

## Social previews

Every page gets a 1200 × 630 image with its title and description. The docs build generates it
from the page metadata, the bundled Inter font and the site logo. Set a front matter
`description` when the first paragraph is not a useful summary of the page.

The renderer uses `static/fonts/inter-latin.ttf`, decoded from the browser font
`inter-latin.woff2`. Update both copies when changing Inter; the Linux image renderer needs
the TrueType file.

`make docs-social-check` checks the renderer. `make docs-build` checks the generated images and
the Open Graph and Twitter tags, including the candidate site paths.

## llms.txt

`docs-site/llms.txt` is the map a coding agent or chat model reads first: what the app is, where
to install, how to make a film, the reference pages and how to build from source. Write its links
site-relative (`/docs/run/nas`). The build turns them into full links for the track it builds, and
fails when a link points to a page that does not exist. Add a page there when it becomes a place
to start; leave detail pages to the sidebar. The build adds a line naming the track, version
and source commit under the summary, and every page links the index from its footer and its
`<head>`.

## Markdown pages

Every docs page also ships as Markdown at its address plus `.md` (`/docs/run/nas/` becomes
`/docs/run/nas.md`), built from the same source. A model reading it should get what a reader sees:
tabs come out as labelled sections, admonitions as quotes, diagrams as text drawings with a list of
their arrows, and screenshots and videos as their alt text, title and full link. A new component
needs a text version in `plugins/page-markdown.mjs`; until it has one, its Markdown says the part
is interactive and links the HTML page. Give every `<Video>` a `title`: it is the video's
alt text on both versions. `make docs-build` checks that no component name or JSX reaches the
Markdown.

## Gates

`make docs-voice`, `make docs-build`, `make docs-cli-check`, `make docs-config-check`.

## Publish docs without an app release

Merge the docs changes, then open **Actions → Deploy Docs → Run workflow** and choose **main**.
The workflow builds that branch and automatically uses the newest published app release for
installation commands and downloads. Release candidates count; drafts, model artifacts and
development-only releases do not. No version input is needed.

The build checks that the chosen release's setup files are uploaded before publishing. A missing
release or incomplete upload stops the workflow and leaves the live site alone. This publishes
only the docs; it does not build or deploy the application.

Until the first final 1.x release, the root is built from main and labelled with the newest
candidate, so docs merged after a candidate's tag still reach the site. Once a final 1.x release
exists, the root is that release's own tree and candidate docs live under `/next/`.

## Website analytics

The docs tracker is bundled in `static/js/app.js`. The Pages workflow reads two GitHub Actions
repository variables at build time: `DOCS_ANALYTICS_DOMAIN` for the Plausible site identifier and
`DOCS_ANALYTICS_ENDPOINT` for the masked event collector URL. Set both under Settings, Secrets
and variables, Actions, Variables. These are public configuration: visitors can read them in the
built HTML and network requests.

With both variables unset, the build loads no tracker. Local builds and forks send no analytics
by default. Setting only one variable fails the build. The script follows the documentation's
base path, including candidate docs under `/next/`.

`make docs-build` checks the built pages and runs the bundled tracker against a fake browser and
collector. CI uses example values; the tests send no network requests. The tracker's source
revision, build variant and MIT notice are recorded in its header.

### Custom events

`src/analytics-events.ts` is a client module. It reads clicks and video events from the page and
calls `window.plausible(name, {props})` only when the tracker is loaded, so builds without the two
variables send nothing. The logic lives in `src/analytics/events.ts`; the tests drive each event
through the real bundled tracker. Props are page paths, tier names, command kinds and file names:
never typed text or a copied command.

| Event | Fired when | Props |
|---|---|---|
| `Install Command Copied` | a code block's copy button is clicked | `page` (path without the base URL), `tier` (`basic`, `gpu`, `full`, or `none` outside the tier tabs), `kind` (`curl`, `docker`, `uv`, `pip`, `kubectl`, `helm`, `other`) |
| `Install Tier Selected` | a tier tab is chosen | `tier` |
| `Demo Played` | a video plays for the first time on a page view (a demo that started by itself counts after the visitor pauses and resumes it) | `video` (file name) |
| `Setup Builder Downloaded` | a generated file is downloaded | `tier`, `file` |
| `Setup Builder Copied` | a generated file is copied | `tier`, `file` |
| `404` | the not-found page renders | `path` (without the base URL) |

Any new event goes in this table and in the table on the website privacy page (`src/pages/privacy.tsx`).

Suggested Plausible setup, done in the Plausible UI by the maintainer. Goals: the events above,
plus `Outbound Link: Click` filtered to the GitHub releases URL. Funnel: the landing page, then the
`/docs/get-started/quick-start` pageview, then `Install Command Copied`. Custom properties need
registering under the site's Goals settings before the dashboard breaks them down.
